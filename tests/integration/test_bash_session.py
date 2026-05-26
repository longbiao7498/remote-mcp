import time
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.bash_session import BashSession


@pytest.fixture
def session(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        bash_timeout_default=10,
    )
    conn = SSHConnection(cfg)
    conn.connect()
    s = BashSession(conn._transport, cfg)
    s.start()
    yield s
    s.close()
    conn.close()


def test_start_creates_running_channel(session):
    assert session._channel is not None
    assert not session._channel.closed
