import shlex
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


def test_execute_echo(session):
    result = session.execute("echo hello")
    assert result.output.strip() == "hello"
    assert result.exit_code == 0


def test_execute_persists_cwd(session):
    session.execute("cd /tmp")
    result = session.execute("pwd")
    assert result.output.strip() == "/tmp"
    assert session.current_cwd() == "/tmp"


def test_execute_persists_env(session):
    session.execute("export FOO=bar_value_xyz")
    result = session.execute("echo $FOO")
    assert result.output.strip() == "bar_value_xyz"


def test_execute_special_chars_roundtrip(session):
    # Use a heredoc-free shell-quoted string with quotes, dollar, backslash
    raw = "it's a $test \"quoted\" \\backslash"
    # Use printf %s with shlex.quote for correct bash quoting (repr() produces
    # Python-style escaping which is invalid bash for strings with single quotes)
    result = session.execute(f"printf '%s' {shlex.quote(raw)}")
    # The output should be exactly the raw string
    assert raw in result.output


def test_execute_nonzero_exit(session):
    result = session.execute("false")
    assert result.exit_code == 1


def test_execute_captures_cwd_change_in_same_command(session):
    result = session.execute("cd /var && pwd")
    assert result.output.strip() == "/var"
    assert session.current_cwd() == "/var"
