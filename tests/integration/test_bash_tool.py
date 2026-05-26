import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import bash as bash_tool


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        bash_timeout_default=15,
    )
    c = SSHConnection(cfg)
    c.connect()
    yield c
    c.close()


def test_bash_foreground_echo(conn):
    out = bash_tool.bash(conn, "echo hi")
    assert "[host=test cwd=" in out
    assert "hi" in out


def test_bash_foreground_persists_cwd(conn):
    bash_tool.bash(conn, "cd /tmp")
    out = bash_tool.bash(conn, "pwd")
    assert "cwd=/tmp" in out
    assert "/tmp" in out


def test_bash_foreground_nonzero_exit(conn):
    out = bash_tool.bash(conn, "false")
    assert "[Exit code: 1]" in out


def test_bash_foreground_output_cap(conn):
    conn.config.bash_output_cap = 200
    out = bash_tool.bash(conn, "yes hello | head -1000")
    # Total length should be bounded by cap + truncation message
    assert "[truncated to" in out


def test_bash_foreground_timeout(conn):
    out = bash_tool.bash(conn, "sleep 100", timeout=2)
    assert out.startswith("Error: Command timed out")
    assert "on test" in out
