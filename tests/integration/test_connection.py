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


@pytest.fixture(scope="module")
def permissive_sshd(sshd_container, ssh_key):
    """
    Start a secondary sshd on the remote host at 127.0.0.1:2222 with no
    AllowUsers restriction.  The main sshd uses an AllowUsers ACL that blocks
    loopback-sourced connections (source is 127.0.0.1 when jump == target), so
    the self-jump test needs its own permissive daemon on a non-standard port.

    Returns the port (2222) on which the inner sshd listens.
    """
    import io
    import paramiko
    import time

    INNER_PORT = 2222
    WORK_DIR = "/tmp/rmcp-sshd-jump"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        sshd_container["host"],
        port=sshd_container["port"],
        username=sshd_container["user"],
        key_filename=ssh_key["private_path"],
    )

    # Prepare work dir and generate a host key
    _, out, _ = client.exec_command(
        f"pkill -f 'sshd -f {WORK_DIR}/sshd_config' 2>/dev/null; "
        f"rm -rf {WORK_DIR} && mkdir -p {WORK_DIR} && "
        f"ssh-keygen -t ed25519 -f {WORK_DIR}/host_key -N '' -q && echo ok"
    )
    assert out.read().decode().strip() == "ok", "Failed to set up sshd work dir"

    # Write sshd config via SFTP (avoids shell quoting issues with heredoc)
    sshd_config = (
        f"Port {INNER_PORT}\n"
        f"ListenAddress 127.0.0.1\n"
        f"HostKey {WORK_DIR}/host_key\n"
        f"AuthorizedKeysFile /thfs1/home/%u/.ssh/authorized_keys\n"
        f"AllowUsers *\n"
        f"PasswordAuthentication no\n"
        f"PubkeyAuthentication yes\n"
        f"UsePAM no\n"
        f"StrictModes no\n"
        f"PidFile {WORK_DIR}/sshd.pid\n"
        f"LogLevel ERROR\n"
    )
    sftp = client.open_sftp()
    with sftp.open(f"{WORK_DIR}/sshd_config", "w") as f:
        f.write(sshd_config)
    sftp.close()

    # Start sshd as a daemon
    _, out, err = client.exec_command(
        f"setsid /usr/sbin/sshd -f {WORK_DIR}/sshd_config -E {WORK_DIR}/sshd.log"
    )
    out.channel.recv_exit_status()

    # Wait for sshd to start listening
    for _ in range(20):
        time.sleep(0.3)
        _, poll, _ = client.exec_command(
            f"ss -tlnp 2>/dev/null | grep ':{INNER_PORT}' | wc -l"
        )
        if poll.read().decode().strip() != "0":
            break
    else:
        _, log, _ = client.exec_command(f"cat {WORK_DIR}/sshd.log 2>/dev/null")
        pytest.fail(f"Inner sshd failed to start. Log:\n{log.read().decode()}")

    client.close()
    yield INNER_PORT

    # Teardown: kill the inner sshd and clean up
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            sshd_container["host"],
            port=sshd_container["port"],
            username=sshd_container["user"],
            key_filename=ssh_key["private_path"],
        )
        _, out, _ = client.exec_command(
            f"pkill -f 'sshd -f {WORK_DIR}/sshd_config' 2>/dev/null; rm -rf {WORK_DIR}; echo done"
        )
        out.channel.recv_exit_status()
        client.close()
    except Exception:
        pass


def test_connect_via_jump_host(sshd_container, ssh_key, permissive_sshd):
    """
    Self-jump: target is the same host as jump. Tests the ProxyJump code path
    (open_channel direct-tcpip + sock= kwarg).

    The main sshd has AllowUsers rules that deny loopback-sourced connections,
    so a secondary permissive sshd is started on 127.0.0.1:2222 for the inner
    leg.  The code path exercised (open_channel + sock=) is identical to a real
    two-host ProxyJump.
    """
    from remote_mcp.config import HostConfig

    jump_cfg = HostConfig(
        name="jump",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    target_cfg = HostConfig(
        name="target",
        # 'localhost' here means localhost from the jump host's perspective —
        # since jump host == target host, this loops back to the same sshd
        # (running on port 2222 with no AllowUsers restriction).
        hostname="127.0.0.1",
        port=permissive_sshd,
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        jump_host="jump",
    )

    conn = SSHConnection(target_cfg, jump_config=jump_cfg)
    conn.connect()
    try:
        result = conn.exec("hostname")
        assert result.exit_code == 0
        assert result.stdout.strip()
    finally:
        conn.close()
