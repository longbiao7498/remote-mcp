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


def test_remote_info_output_is_5_lines():
    """Output is exactly the 5 documented fields, one per line."""
    cfg = HostConfig(name="x", hostname="h", user="u")
    out = remote_info(_FakeConn(cfg))
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 5
    field_names = {l.split("=", 1)[0] for l in lines}
    assert field_names == {"host", "user", "hostname", "port", "jump_host"}


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
