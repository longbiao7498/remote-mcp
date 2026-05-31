"""Unit tests for RemoteInfo — pure config formatting, no SSH."""
from remote_mcp.config import HostConfig
from remote_mcp.tools.remote_info import remote_info


class _FakeConn:
    def __init__(self, config):
        self.config = config


def test_remote_info_minimal_config():
    cfg = HostConfig(name="prod", hostname="10.0.0.1", user="ubuntu")
    out = remote_info(_FakeConn(cfg))
    assert "host=prod" in out
    assert "user=ubuntu" in out
    assert "hostname=10.0.0.1" in out
    assert "port=22" in out
    assert "jump_host=none" in out


def test_remote_info_full_config_with_jump():
    cfg = HostConfig(
        name="internal",
        hostname="10.0.0.50",
        user="admin",
        port=2222,
        jump_host="bastion",
    )
    out = remote_info(_FakeConn(cfg))
    assert "host=internal" in out
    assert "user=admin" in out
    assert "hostname=10.0.0.50" in out
    assert "port=2222" in out
    assert "jump_host=bastion" in out


def test_remote_info_output_is_7_lines():
    """Output is exactly the 7 documented fields, one per line (cwd added in v0.2.0; sid added in v0.3.0)."""
    cfg = HostConfig(name="x", hostname="h", user="u")
    out = remote_info(_FakeConn(cfg))
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 7
    # sid line uses ": " separator, others use "=" — check all expected fields present
    assert any(l.startswith("sid: ") for l in lines)
    eq_field_names = {l.split("=", 1)[0] for l in lines if "=" in l and not l.startswith("sid")}
    assert eq_field_names == {"host", "user", "hostname", "port", "jump_host", "cwd"}


def test_remote_info_no_ssh_calls_made():
    """
    RemoteInfo must NOT touch the connection. This is the VPN-safety
    guarantee: even if SSH is dead, the result is the configured
    identity (the one we connect TO), not what the remote reports.
    """
    cfg = HostConfig(name="prod", hostname="vpn-internal", user="alice")
    # Fake conn that raises if anyone tries to use it
    class _NoSSHConn:
        def __init__(self, config): self.config = config
        def __getattr__(self, name):
            raise AssertionError(f"RemoteInfo touched the connection: .{name}")

    out = remote_info(_NoSSHConn(cfg))
    assert "host=prod" in out


def test_remote_info_includes_cwd():
    from remote_mcp.tools.remote_info import remote_info
    from types import SimpleNamespace
    conn = SimpleNamespace(
        config=SimpleNamespace(
            name="prod", user="deploy", hostname="prod.example.com",
            port=22, jump_host="bastion", cwd="/opt/myapp",
        ),
    )
    out = remote_info(conn)
    assert "cwd=/opt/myapp" in out


def test_remote_info_cwd_when_none():
    # If cwd is somehow None at runtime (shouldn't happen after connect, but
    # be defensive), show 'unknown' rather than crash
    from remote_mcp.tools.remote_info import remote_info
    from types import SimpleNamespace
    conn = SimpleNamespace(
        config=SimpleNamespace(
            name="x", user="u", hostname="h", port=22,
            jump_host=None, cwd=None,
        ),
    )
    out = remote_info(conn)
    assert "cwd=unknown" in out


def test_remote_info_includes_sid_line():
    from remote_mcp.tools.remote_info import remote_info
    from remote_mcp.config import HostConfig

    class _StubConn:
        def __init__(self):
            self.config = HostConfig(
                name="testhost", hostname="example.com",
                port=22, user="alice", cwd="/home/alice",
            )

    out = remote_info(_StubConn())
    import re
    assert re.search(r"^sid: [0-9a-f]{12} \(source=", out, re.MULTILINE)
