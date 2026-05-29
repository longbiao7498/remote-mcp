"""bug #2 — SFTP/exec ops must respect op_timeout_default. v0.2.2."""
import socket
import threading
import time

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection


@pytest.fixture
def conn_short_timeout(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        op_timeout_default=2,  # very short for fast tests
    )
    c = SSHConnection(cfg)
    c.connect()
    yield c
    c.close()


def test_exec_recv_timeout_raises_socket_timeout(conn_short_timeout):
    """Running a command that produces no output for >op_timeout_default
    should make conn.exec() raise socket.timeout (OSError subclass)."""
    start = time.monotonic()
    with pytest.raises((socket.timeout, OSError)):
        # sleep 30 + then echo — silent for 30s, way past 2s op_timeout
        conn_short_timeout.exec("sleep 30; echo DONE")
    elapsed = time.monotonic() - start
    # Must give up within ~3s (2s timeout + a bit of overhead)
    assert elapsed < 5.0, f"exec waited {elapsed:.2f}s, expected <5s"


def test_sftp_channel_has_timeout_set(conn_short_timeout):
    """SFTP channel must have settimeout applied so a stalled remote
    can't block forever."""
    sftp = conn_short_timeout.get_sftp()
    ch = sftp.get_channel()
    # paramiko stores the timeout on the channel
    assert ch.gettimeout() == 2.0, (
        f"SFTP channel timeout is {ch.gettimeout()}, expected 2.0"
    )
