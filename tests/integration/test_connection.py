import pytest
from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection


@pytest.fixture
def host_config(sshd_container, ssh_key):
    return HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        keepalive_interval=10,
        compression=True,
    )


def test_connect_succeeds(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        assert conn._transport is not None
        assert conn._transport.is_active()
    finally:
        conn.close()


def test_connect_enables_keepalive(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        # paramiko 5.x stores the interval in the packetizer (no public getter).
        # Access via the name-mangled private attribute on Packetizer.
        interval = conn._transport.packetizer._Packetizer__keepalive_interval
        assert interval == 10
    finally:
        conn.close()


def test_connect_enables_compression(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        # After handshake, local_compression should be a non-trivial codec name
        # (paramiko uses 'zlib@openssh.com' or 'zlib' when negotiated)
        assert conn._transport.local_compression not in (None, "none")
    finally:
        conn.close()


def test_close_releases_transport(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    conn.close()
    assert conn._transport is None or not conn._transport.is_active()


def test_exec_echo_hello(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        result = conn.exec("echo hello")
        assert result.stdout == "hello\n"
        assert result.exit_code == 0
        assert result.stderr == ""
    finally:
        conn.close()


def test_exec_nonzero_exit(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        result = conn.exec("cat /nonexistent/file")
        assert result.exit_code != 0
        assert "No such file" in result.stderr or "No such" in result.stderr
    finally:
        conn.close()


def test_exec_captures_stderr_separately(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        result = conn.exec("echo to_stdout; echo to_stderr >&2")
        assert "to_stdout" in result.stdout
        assert "to_stderr" in result.stderr
    finally:
        conn.close()
