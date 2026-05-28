"""SSH connection lifecycle. See spec §5.1, §5.1.1."""
from dataclasses import dataclass
from typing import Optional

import paramiko

from .config import HostConfig


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SSHConnection:
    def __init__(self, config: HostConfig, jump_config: Optional[HostConfig] = None):
        self.config = config
        self.jump_config = jump_config
        self._transport: Optional[paramiko.Transport] = None
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._jump_client: Optional[paramiko.SSHClient] = None
        self._reconnected: bool = False
        self._bash_session = None
        self._snapshot_path: Optional[str] = None

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

        self._create_snapshot()

    def get_bash_session(self):
        from .bash_session import BashSession
        if self._bash_session is None:
            if self._client is None or self._transport is None:
                raise RuntimeError("SSHConnection not connected")
            self._bash_session = BashSession(self._transport, self.config)
            self._bash_session.start()
        return self._bash_session

    def _create_snapshot(self) -> None:
        """Dump shell environment to /tmp/rmcp-snapshot-<host>-<pid>.sh on remote.

        Per spec §5.1: bash -ic loads ~/.bashrc once; declare -p / declare -fp /
        alias capture vars, functions, aliases. Written via SFTP (not heredoc) to
        avoid quoting hell. PID is the LOCAL MCP server process pid so concurrent
        MCP instances against the same remote don't collide.

        Failure to create snapshot is a warning (logged) not a fatal error —
        Bash invocations will run without snapshot (loses user PATH/aliases)
        but still work. See Task B5 for the cwd cd appendix.
        """
        import os
        pid = os.getpid()
        path = f"/tmp/rmcp-snapshot-{self.config.name}-{pid}.sh"
        self._snapshot_path = path

        # `2>/dev/null` on the inner commands suppresses bashrc-emitted noise
        # (some users print to stderr in bashrc)
        cmd = (
            "bash -ic 'declare -p 2>/dev/null; declare -fp 2>/dev/null; "
            "alias 2>/dev/null'"
        )

        try:
            result = self.exec(cmd, timeout=30.0)
            content = result.stdout
            sftp = self.get_sftp()
            with sftp.file(path, "w") as f:
                f.write(content.encode("utf-8"))
        except Exception as e:
            import sys
            print(
                f"[remote-mcp] WARNING: snapshot creation failed on "
                f"{self.config.name}: {e}; Bash will run without snapshot",
                file=sys.stderr,
            )
            self._snapshot_path = None

    def exec(self, command: str, timeout: float = 30.0) -> ExecResult:
        """One-shot exec. Opens a new channel, runs cmd, closes."""
        if self._client is None:
            raise RuntimeError("SSHConnection not connected; call connect() first")
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
        return self._sftp

    def check_and_clear_reconnect_flag(self) -> bool:
        flag = self._reconnected
        self._reconnected = False
        return flag

    def _do_reconnect(self) -> None:
        """Tear down (if needed) and rebuild. Sets _reconnected=True on success.
        connect() re-runs _create_snapshot() which overwrites the old file."""
        self.close()
        self.connect()
        self._reconnected = True

    def exec_with_retry(self, command: str, timeout: float = 30.0) -> ExecResult:
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
        # Best-effort snapshot cleanup (must happen BEFORE channels close)
        if self._snapshot_path is not None and self._client is not None:
            try:
                self.exec(f"rm -f {self._snapshot_path}", timeout=5.0)
            except Exception:
                pass
            self._snapshot_path = None
        if self._bash_session is not None:
            try:
                self._bash_session.close()
            except Exception:
                pass
            self._bash_session = None
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
