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


def test_get_sftp_returns_client(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        sftp = conn.get_sftp()
        # Use it: list home dir
        listing = sftp.listdir(".")
        assert isinstance(listing, list)
    finally:
        conn.close()


def test_get_sftp_returns_same_instance(host_config):
    """Verify lazy + cached (no new channel per call)."""
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        s1 = conn.get_sftp()
        s2 = conn.get_sftp()
        assert s1 is s2
    finally:
        conn.close()


@pytest.mark.skip(
    reason="Self-jump test infeasible on the current test host: main sshd has "
    "AllowUsers ACL that rejects loopback-sourced connections. Spawning a "
    "secondary permissive sshd was prototyped but rejected as too invasive "
    "(leaves a daemon process on a shared host). ProxyJump code path is "
    "verifiable by inspection — paramiko boilerplate (open_channel "
    "direct-tcpip + sock= kwarg). Re-enable when a host with two-IP setup "
    "or a second host becomes available."
)
def test_connect_via_jump_host(sshd_container, ssh_key):
    """ProxyJump verification — skipped, see decorator."""
    pass


def test_reconnect_flag_initially_false(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        assert conn.check_and_clear_reconnect_flag() is False
    finally:
        conn.close()


def test_exec_with_retry_recovers_after_disconnect(host_config, sshd_kill_and_restart):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        # First call: succeeds
        assert conn.exec_with_retry("echo first").stdout.strip() == "first"
        assert conn.check_and_clear_reconnect_flag() is False

        # Force-close the underlying TCP socket; next op must trigger reconnect
        sshd_kill_and_restart(conn)
        result = conn.exec_with_retry("echo second")
        assert result.stdout.strip() == "second"

        # Reconnect flag was set; check_and_clear consumes it
        assert conn.check_and_clear_reconnect_flag() is True
        # Second check: cleared
        assert conn.check_and_clear_reconnect_flag() is False
    finally:
        conn.close()


def test_get_bash_session_lazy_singleton(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        s1 = conn.get_bash_session()
        s2 = conn.get_bash_session()
        assert s1 is s2
        # Verify it works
        result = s1.execute("echo via_connection")
        assert "via_connection" in result.output
    finally:
        conn.close()


def test_reconnect_invalidates_bash_session(host_config, sshd_kill_and_restart):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        s_pre = conn.get_bash_session()
        s_pre.execute("cd /tmp")

        sshd_kill_and_restart(conn)

        # exec_with_retry forces reconnect
        conn.exec_with_retry("echo touchstone")

        # Now get_bash_session should return a NEW session (state reset)
        s_post = conn.get_bash_session()
        assert s_post is not s_pre
        # cwd reset to $HOME
        result = s_post.execute("pwd")
        assert result.output.strip() != "/tmp"
    finally:
        conn.close()


def test_snapshot_created_on_connect(sshd_container, ssh_key):
    from remote_mcp.config import HostConfig
    from remote_mcp.connection import SSHConnection
    cfg = HostConfig(
        name="snaptest",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    try:
        # Snapshot path should be set
        assert c._snapshot_path is not None
        assert c._snapshot_path.startswith("/tmp/rmcp-snapshot-snaptest-")
        assert c._snapshot_path.endswith(".sh")
        # File should exist on remote
        r = c.exec(f"test -f {c._snapshot_path} && echo OK")
        assert r.stdout.strip() == "OK"
        # Snapshot content includes at least one `declare` line
        r = c.exec(f"head -5 {c._snapshot_path}")
        assert "declare" in r.stdout
    finally:
        c.close()


def test_snapshot_removed_on_close(sshd_container, ssh_key):
    """After close(), the snapshot file must be gone. Verify with a raw
    paramiko client (NOT a second SSHConnection, which would create a new
    snapshot at the same path and defeat the test)."""
    from remote_mcp.config import HostConfig
    from remote_mcp.connection import SSHConnection
    import paramiko

    cfg = HostConfig(
        name="snaptest2",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    snap_path = c._snapshot_path
    c.close()

    # Verify via raw paramiko (no snapshot side-effects)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        sshd_container["host"],
        port=sshd_container["port"],
        username=sshd_container["user"],
        key_filename=ssh_key["private_path"],
        timeout=5,
    )
    try:
        stdin, stdout, _ = client.exec_command(
            f"test -f {snap_path} && echo PRESENT || echo GONE"
        )
        out = stdout.read().decode().strip()
        assert out == "GONE", f"snapshot still exists at {snap_path}"
    finally:
        client.close()


def test_snapshot_rebuilt_after_reconnect(sshd_container, ssh_key, sshd_kill_and_restart):
    """After _do_reconnect(), the snapshot must exist again with a valid path.
    A2 relies on _snapshot_path staying non-None across reconnects."""
    from remote_mcp.config import HostConfig
    from remote_mcp.connection import SSHConnection

    cfg = HostConfig(
        name="snaprc",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    try:
        path_before = c._snapshot_path
        assert path_before is not None

        # Simulate dropped connection
        sshd_kill_and_restart(c)

        # Trigger reconnect via the retry helper
        r = c.exec_with_retry("echo OK")
        assert r.stdout.strip() == "OK"

        # Snapshot path is set again (same path, since PID unchanged)
        assert c._snapshot_path is not None
        assert c._snapshot_path == path_before

        # And the file actually exists on remote
        r = c.exec(f"test -f {c._snapshot_path} && echo OK")
        assert r.stdout.strip() == "OK"
    finally:
        c.close()
