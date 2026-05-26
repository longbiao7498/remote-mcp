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
                j_kwargs["key_filename"] = self.jump_config.key_path
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
            connect_kwargs["key_filename"] = self.config.key_path
        if self.config.password:
            connect_kwargs["password"] = self.config.password
        client.connect(**connect_kwargs)

        self._client = client
        self._transport = client.get_transport()
        if self.config.keepalive_interval > 0:
            self._transport.set_keepalive(self.config.keepalive_interval)

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

    def close(self) -> None:
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
