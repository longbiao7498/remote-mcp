"""Integration test fixtures: real remote host (no docker).

The fixture targets a pre-configured host at 192.168.10.20 reachable
passwordlessly from this dev machine. All filesystem side-effects go
into /tmp/rmcp-test-<uuid>/ which is cleaned up at session end.
"""
import os
import subprocess
import uuid
from pathlib import Path

import paramiko
import pytest


REMOTE_HOST = os.environ.get("RMCP_TEST_HOST", "192.168.10.20")
REMOTE_USER = os.environ.get("RMCP_TEST_USER", "penglin_lb")
REMOTE_PORT = int(os.environ.get("RMCP_TEST_PORT", "22"))
REMOTE_KEY = os.environ.get(
    "RMCP_TEST_KEY", os.path.expanduser("~/.ssh/id_ed25519")
)


@pytest.fixture(scope="session")
def ssh_key():
    """Path to the SSH private key for the test host."""
    if not Path(REMOTE_KEY).exists():
        pytest.skip(f"SSH key not found at {REMOTE_KEY}")
    return {"private_path": REMOTE_KEY}


@pytest.fixture(scope="session")
def sshd_container(ssh_key):
    """
    Connection params to the real remote host (name kept for legacy plan
    compatibility — it's NOT actually a container).

    Session-scoped: one connection-test verifies reachability, then yields
    params. The session-scoped working dir is created on the remote and
    removed at teardown.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER,
            key_filename=ssh_key["private_path"], timeout=5,
        )
    except Exception as e:
        pytest.skip(f"Remote host {REMOTE_HOST} unreachable: {e}")

    session_id = uuid.uuid4().hex[:12]
    workdir = f"/tmp/rmcp-test-{session_id}"
    stdin, stdout, _ = client.exec_command(f"mkdir -p {workdir}")
    assert stdout.channel.recv_exit_status() == 0
    client.close()

    yield {
        "host": REMOTE_HOST,
        "port": REMOTE_PORT,
        "user": REMOTE_USER,
        "key_path": ssh_key["private_path"],
        "workdir": workdir,
    }

    # Teardown: remove session workdir
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER,
            key_filename=ssh_key["private_path"], timeout=5,
        )
        client.exec_command(f"rm -rf {workdir}")
        client.close()
    except Exception:
        pass  # Best-effort cleanup


@pytest.fixture
def sshd_kill_and_restart(sshd_container):
    """
    Helper for reconnect tests.

    Returns a callable that, when invoked with an SSHConnection-like object,
    force-closes its underlying TCP socket. The next paramiko operation will
    see the dead socket and raise — triggering the reconnect path.

    Equivalent test signal to "the remote dropped the connection", with zero
    side effects on the shared remote host.
    """
    def _action(conn=None):
        if conn is not None and getattr(conn, "_transport", None) is not None:
            sock = conn._transport.sock
            try:
                sock.close()
            except Exception:
                pass
            try:
                conn._transport.close()
            except Exception:
                pass
    return _action


@pytest.fixture
def flaky_proxy(sshd_container):
    """In-process TCP proxy listening on 127.0.0.1:<ephemeral>, forwarding to
    the real remote sshd. Tests can call drop_all/close_now/limit_bytes_from_remote
    to simulate network anomalies without touching paramiko or remote-mcp code.

    See tests/integration/flaky_proxy.py for control API.
    """
    from .flaky_proxy import FlakyTCPProxy
    proxy = FlakyTCPProxy(
        target_host=sshd_container["host"],
        target_port=sshd_container["port"],
    )
    yield proxy
    proxy.shutdown()


@pytest.fixture
def conn_via_proxy(flaky_proxy, ssh_key, sshd_container):
    """SSHConnection pointed at the flaky proxy instead of the real remote.
    Snapshot is captured at fixture init so v0.2.2 startup invariants hold."""
    from remote_mcp.config import HostConfig
    from remote_mcp.connection import SSHConnection

    cfg = HostConfig(
        name="proxytest",
        hostname="127.0.0.1",
        port=flaky_proxy.local_port,
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        connect_timeout=10.0,
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    yield c
    c.close()
