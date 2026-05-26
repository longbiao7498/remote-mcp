"""Persistent bash session with sentinel protocol. See spec §5.2."""
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import paramiko

from .config import HostConfig


_SENTINEL_RE = re.compile(
    r"^RMCP_SENTINEL_([a-zA-Z0-9]+)_EXIT_(\d+)_CWD_(.*)$"
)


def parse_sentinel_line(line: str, expected_uuid: str):
    """
    If `line` is a sentinel matching expected_uuid, return (exit_code, cwd).
    Otherwise return None.
    """
    m = _SENTINEL_RE.match(line.rstrip("\n"))
    if not m:
        return None
    uuid_in_line, exit_str, cwd = m.groups()
    if uuid_in_line != expected_uuid:
        return None
    return int(exit_str), cwd


_INIT_SEQUENCE = (
    "set +m\n"
    "set +o histexpand\n"
    "export PS1=''\n"
    "export TERM=dumb\n"
    "exec 2>&1\n"
)


@dataclass
class BashResult:
    output: str
    exit_code: int


class BashSession:
    def __init__(self, transport: paramiko.Transport, config: HostConfig):
        self._transport = transport
        self.config = config
        self._channel: Optional[paramiko.Channel] = None
        self._output_queue: "queue.Queue[bytes]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()
        self._cwd: str = "~"   # Will be populated after first execute() captures real cwd

    def start(self) -> None:
        ch = self._transport.open_session()
        # Critical: combine stderr+stdout BEFORE bash starts (paramiko-side)
        ch.set_combine_stderr(True)
        ch.exec_command("bash --norc --noprofile")
        self._channel = ch
        # Inject init sequence
        self._channel.sendall(_INIT_SEQUENCE.encode("utf-8"))
        # Start reader (will be needed for execute(); started here so it's safe to call execute next)
        self._start_reader()
        # Drain initial echoes from init sequence so they don't contaminate the first execute()
        # Sleep briefly to let any startup noise flow into the queue.
        time.sleep(0.2)
        # Drain queue
        while not self._output_queue.empty():
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break
        # Capture initial cwd
        try:
            self.execute("true", timeout=5.0)  # captures cwd via sentinel
        except Exception:
            pass

    def _start_reader(self) -> None:
        def reader():
            buf = b""
            while not self._stop_reader.is_set():
                if self._channel is None or self._channel.closed:
                    break
                try:
                    if self._channel.recv_ready():
                        data = self._channel.recv(4096)
                        if not data:
                            break
                        buf += data
                        # Split on \n, queue complete lines
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            self._output_queue.put(line + b"\n")
                    else:
                        # Short sleep to avoid spinning
                        self._stop_reader.wait(0.01)
                except Exception:
                    break
            # Flush any remaining buffer
            if buf:
                self._output_queue.put(buf)

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()

    def execute(self, command: str, timeout: Optional[float] = None) -> BashResult:
        """
        Send command + sentinel echo, read until sentinel arrives.
        Sentinel format: RMCP_SENTINEL_<uuid>_EXIT_$?_CWD_$(pwd)
        Captures exit_code AND cwd in one round-trip.
        """
        if self._channel is None or self._channel.closed:
            raise RuntimeError("BashSession not started or channel closed")
        if timeout is None:
            timeout = float(self.config.bash_timeout_default)

        u = uuid.uuid4().hex
        # Capture $? immediately after the command runs (before printf '\n'
        # which would overwrite it), then emit a newline to guarantee the
        # sentinel appears at the start of a new line even when the command
        # produces output without a trailing newline (e.g. `printf '%s' foo`).
        sentinel_cmd = (
            f'{command}\n'
            f'_RMCP_RC_=$?\n'
            f'printf "\\n"\n'
            f'echo "RMCP_SENTINEL_{u}_EXIT_${{_RMCP_RC_}}_CWD_$(pwd)"\n'
        )
        self._channel.sendall(sentinel_cmd.encode("utf-8"))

        deadline = time.time() + timeout
        output_lines = []
        exit_code = None
        cwd = None

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                # Send Ctrl-C; raise; session survives
                try:
                    self._channel.sendall(b"\x03")
                except Exception:
                    pass
                raise TimeoutError(f"Command timed out after {timeout}s")
            try:
                line_bytes = self._output_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            line = line_bytes.decode("utf-8", errors="replace")
            parsed = parse_sentinel_line(line, u)
            if parsed is not None:
                exit_code, cwd = parsed
                break
            output_lines.append(line)

        output = "".join(output_lines)
        if cwd is not None:
            self._cwd = cwd

        return BashResult(output=output, exit_code=exit_code if exit_code is not None else -1)

    def current_cwd(self) -> str:
        return self._cwd

    def close(self) -> None:
        self._stop_reader.set()
        if self._channel is not None and not self._channel.closed:
            try:
                self._channel.close()
            except Exception:
                pass
            self._channel = None
