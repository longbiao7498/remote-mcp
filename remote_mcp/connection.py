"""SSH connection lifecycle. See spec §5.1, §5.1.1."""
import shlex
import socket
import time
from dataclasses import dataclass
from typing import Optional

import paramiko

from .config import HostConfig


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    elapsed_sec: float = 0.0


class SSHConnectionError(Exception):
    """Raised when SSH setup or cwd validation fails fatally."""


class SSHConnection:
    def __init__(self, config: HostConfig, jump_config: Optional[HostConfig] = None):
        self.config = config
        self.jump_config = jump_config
        self._transport: Optional[paramiko.Transport] = None
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._jump_client: Optional[paramiko.SSHClient] = None
        self._reconnected: bool = False
        self._snapshot_path: Optional[str] = None
        # v0.2.2 snapshot fields
        self._snapshot_content: Optional[bytes] = None
        self._snapshot_error: Optional[str] = None
        self._remote_home: Optional[str] = None
        self._snapshot_reuploaded: bool = False
        self._startup_warning_pending: bool = False

    def connect(self) -> None:
        """Build the SSH client + Transport. Idempotent: closes any prior."""
        if self._client is not None:
            self.close()

        sock = None
        if self.jump_config is not None:
            self._jump_client = paramiko.SSHClient()
            self._jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            j_kwargs = {
                "hostname": self.jump_config.hostname,
                "port": self.jump_config.port,
                "username": self.jump_config.user,
                "timeout": self.jump_config.connect_timeout,
            }
            if self.jump_config.key_path:
                import os
                j_kwargs["key_filename"] = os.path.expanduser(self.jump_config.key_path)
            self._jump_client.connect(**j_kwargs)
            sock = self._jump_client.get_transport().open_channel(
                "direct-tcpip",
                (self.config.hostname, self.config.port),
                ("localhost", 0),
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.config.hostname,
            "port": self.config.port,
            "username": self.config.user,
            "timeout": self.config.connect_timeout,
            "compress": self.config.compression,
        }
        if sock is not None:
            connect_kwargs["sock"] = sock
        if self.config.key_path:
            import os
            connect_kwargs["key_filename"] = os.path.expanduser(self.config.key_path)
        if self.config.password:
            connect_kwargs["password"] = self.config.password
        client.connect(**connect_kwargs)

        self._client = client
        self._transport = client.get_transport()
        if self.config.keepalive_interval > 0:
            self._transport.set_keepalive(self.config.keepalive_interval)

        # --- v0.2.0: cwd resolution and validation (spec §6.2, §6.4) ---
        self._resolve_and_validate_cwd()

    def _resolve_and_validate_cwd(self) -> None:
        """Apply ~ expansion + format check + SFTP stat (spec §6.2, §6.4)."""
        cwd = self.config.cwd if self.config.cwd is not None else "~"

        # Format check: only allow absolute paths, ~, or ~/...
        if not (cwd == "~" or cwd.startswith("/") or cwd.startswith("~/")):
            raise SSHConnectionError(
                f"cwd must be an absolute path or start with '~/' "
                f"(got: '{cwd}'). Valid: /opt/app, ~/projects/myapp, ~"
            )

        # ~ expansion
        if cwd == "~" or cwd.startswith("~/"):
            home = self._resolve_remote_home()
            cwd = home if cwd == "~" else home + cwd[1:]

        # Write back so RemoteInfo / suffix / snapshot all see the same value
        self.config.cwd = cwd

        # SFTP stat — does not depend on remote shell
        import stat as _stat
        sftp = self.get_sftp()
        try:
            st = sftp.stat(cwd)
        except IOError:
            raise SSHConnectionError(
                f"configured cwd '{cwd}' does not exist on host "
                f"'{self.config.name}'. Fix the --cwd argument or remove it "
                f"to use $HOME."
            )
        if not _stat.S_ISDIR(st.st_mode or 0):
            raise SSHConnectionError(
                f"configured cwd '{cwd}' exists on host "
                f"'{self.config.name}' but is not a directory."
            )

    def _resolve_remote_home(self) -> str:
        """Query remote $HOME via bash -c (per spec §6.2). Cached after first call."""
        if self._remote_home is not None:
            return self._remote_home
        r = self.exec("bash -c 'echo $HOME'", timeout=10.0)
        home = r.stdout.strip()
        if not home or not home.startswith("/"):
            raise SSHConnectionError(
                f"could not resolve remote $HOME on host "
                f"'{self.config.name}' (got: {home!r})"
            )
        self._remote_home = home
        return home

    def _capture_snapshot(self) -> None:
        """Run bash -ic once, cache content locally, upload to remote ~/.cache/.

        Called once at MCP server startup (from server.main). NOT called by
        connect() — reconnect doesn't recapture; see _do_reconnect for re-upload
        logic when the remote file is found missing.
        """
        import shlex
        self._snapshot_error = None
        self._snapshot_content = None
        self._snapshot_path = None
        try:
            # Ensure _remote_home is populated — needed by _upload_snapshot_to_remote.
            # _resolve_and_validate_cwd only calls _resolve_remote_home when cwd
            # contains ~; for absolute cwd (e.g. /tmp) it is not called, so we
            # do it explicitly here.
            self._resolve_remote_home()
            cmd = (
                "bash -ic 'declare -p 2>/dev/null; declare -fp 2>/dev/null; "
                "alias 2>/dev/null'"
            )
            result = self.exec(cmd, timeout=30.0)
            content = result.stdout
            if self.config.cwd:
                content += f"\ncd {shlex.quote(self.config.cwd)} || exit 1\n"
            self._snapshot_content = content.encode("utf-8")
        except Exception as e:
            self._snapshot_error = f"snapshot capture failed: {e}"
            return
        self._upload_snapshot_to_remote()

    def _upload_snapshot_to_remote(self) -> None:
        """Upload cached content to remote ~/.cache/remote-mcp/snapshot-<pid>.sh.

        Idempotent: always overwrites. Creates ~/.cache/remote-mcp/ via SFTP
        mkdir -p semantics if missing. On any failure (mkdir, write, permission,
        disk full) sets _snapshot_error and clears _snapshot_path.
        """
        if self._snapshot_content is None:
            return
        if self._remote_home is None:
            self._snapshot_error = "snapshot upload failed: remote home unresolved"
            self._snapshot_path = None
            return
        import os
        cache_dir = f"{self._remote_home}/.cache/remote-mcp"
        pid = os.getpid()
        path = f"{cache_dir}/snapshot-{pid}.sh"
        try:
            sftp = self.get_sftp()
            from .tools.write import _sftp_mkdirs
            _sftp_mkdirs(sftp, cache_dir)
            with sftp.file(path, "w") as f:
                f.write(self._snapshot_content)
            self._snapshot_path = path
            self._snapshot_error = None
        except Exception as e:
            self._snapshot_error = f"snapshot upload failed: {e}"
            self._snapshot_path = None

    def _snapshot_exists_on_remote(self) -> bool:
        """Check whether the remote snapshot file is still present.

        Single SFTP stat call. Returns False on IOError (paramiko raises
        IOError for missing files).
        """
        if self._snapshot_path is None:
            return False
        try:
            sftp = self.get_sftp()
            sftp.stat(self._snapshot_path)
            return True
        except IOError:
            return False

    def exec(self, command: str, timeout: Optional[float] = None) -> ExecResult:
        """One-shot exec. Opens a new channel, runs cmd, closes.

        timeout=None means use self.config.op_timeout_default. The value is
        passed to paramiko's exec_command which sets channel.settimeout —
        i.e. "no bytes for <timeout> seconds → socket.timeout raised".
        """
        if self._client is None:
            raise RuntimeError("SSHConnection not connected; call connect() first")
        if timeout is None:
            timeout = float(self.config.op_timeout_default)
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return ExecResult(stdout=out, stderr=err, exit_code=exit_code)

    def get_sftp(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            if self._client is None:
                raise RuntimeError("SSHConnection not connected")
            self._sftp = self._client.open_sftp()
            self._sftp.get_channel().settimeout(float(self.config.op_timeout_default))
        return self._sftp

    def check_and_clear_reconnect_flag(self) -> bool:
        flag = self._reconnected
        self._reconnected = False
        return flag

    def _do_reconnect(self) -> None:
        """Tear down channels and rebuild SSH layer. Snapshot file is preserved
        in ~/.cache/ — re-uploaded from local cache only if remote file is
        missing. Sets _reconnected=True on success.
        """
        self.close()
        self.connect()
        # Snapshot: check remote, re-upload from local cache only if missing.
        # Never re-capture (would re-run bash -ic and pick up bashrc changes).
        if self._snapshot_content is not None:
            if not self._snapshot_exists_on_remote():
                self._upload_snapshot_to_remote()
                self._snapshot_reuploaded = True
        self._reconnected = True

    def exec_with_retry(self, command: str, timeout: Optional[float] = None) -> ExecResult:
        """exec() with one-shot auto-reconnect on SSH-level failure."""
        try:
            return self.exec(command, timeout=timeout)
        except (paramiko.SSHException, EOFError, OSError) as e:
            try:
                self._do_reconnect()
            except Exception as e2:
                raise ConnectionError(
                    f"SSH connection to {self.config.name} lost and reconnect "
                    f"failed: {e2}"
                ) from e
            return self.exec(command, timeout=timeout)

    def close(self) -> None:
        # v0.2.2: snapshot file is NOT deleted here — it lives in ~/.cache/
        # and persists across MCP runs.
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._transport = None
        if self._jump_client is not None:
            try:
                self._jump_client.close()
            except Exception:
                pass
            self._jump_client = None


def exec_with_snapshot(conn: "SSHConnection", command: str, timeout: float) -> ExecResult:
    """Run command on remote with snapshot sourced + </dev/null.

    Wraps as: bash --noprofile --norc -c 'source <snapshot>; <command>' </dev/null

    Drain stdout/stderr separately; on timeout, channel.close() and return
    partial output with timed_out=True. Caller decides error formatting and
    output capping.

    NOTE: stdout and stderr are drained into separate buffers using alternating
    non-blocking reads. The interleaving order from the remote is NOT preserved —
    callers that want a merged stream must concatenate the two fields themselves
    (e.g. ``result.stdout + result.stderr``). This is intentional: separate buffers
    are required by spec §19.2 for panel/job-status consumers.

    Raises only on SSH-layer exceptions (paramiko.SSHException, OSError).
    """
    snapshot_path = getattr(conn, "_snapshot_path", None)
    if snapshot_path:
        inner = f"source {shlex.quote(snapshot_path)} 2>/dev/null || true; {command}"
    else:
        inner = command
    wrapped = f"bash --noprofile --norc -c {shlex.quote(inner)} </dev/null"

    client = conn._client
    if client is None:
        raise paramiko.SSHException(f"SSH connection to {conn.config.name} not open")

    started = time.time()
    stdin, stdout, stderr = client.exec_command(wrapped, timeout=None)
    channel = stdout.channel
    channel.settimeout(0.2)

    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    deadline = started + timeout
    timed_out = False

    while True:
        if channel.exit_status_ready() and not channel.recv_ready() \
                and not channel.recv_stderr_ready():
            break
        if time.time() > deadline:
            timed_out = True
            break
        try:
            data = channel.recv(4096)
            if data:
                out_chunks.append(data)
                continue
        except socket.timeout:
            pass
        try:
            data = channel.recv_stderr(4096)
            if data:
                err_chunks.append(data)
        except socket.timeout:
            pass

    # Drain whatever's left
    try:
        while channel.recv_ready():
            out_chunks.append(channel.recv(4096))
        while channel.recv_stderr_ready():
            err_chunks.append(channel.recv_stderr(4096))
    except Exception:
        pass

    if timed_out:
        try:
            channel.close()
        except Exception:
            pass
        exit_code = -1
    else:
        exit_code = channel.recv_exit_status()
        try:
            channel.close()
        except Exception:
            pass

    # Includes channel.recv_exit_status() round-trip; not strictly command wall time.
    elapsed = time.time() - started
    stdout_s = b"".join(out_chunks).decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "")
    stderr_s = b"".join(err_chunks).decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "")

    return ExecResult(
        stdout=stdout_s,
        stderr=stderr_s,
        exit_code=exit_code,
        timed_out=timed_out,
        elapsed_sec=elapsed,
    )
