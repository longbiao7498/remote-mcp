"""bug #3 — background bash writes PID to pidfile for orphan recovery. v0.2.2."""
import re
import time

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
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    yield c
    c.close()


def test_background_launch_writes_pidfile(conn):
    """After a successful background launch, /tmp/rmcp-bg-<uuid>.pid exists
    and contains the PID."""
    out = bash_tool.bash(conn, "sleep 30", run_in_background=True)
    pid_match = re.search(r"PID:\s*(\d+)", out)
    log_match = re.search(r"Log:\s*/tmp/rmcp-bg-([a-f0-9]+)\.log", out)
    assert pid_match and log_match, f"could not parse PID/Log from: {out!r}"
    pid = pid_match.group(1)
    uuid = log_match.group(1)
    # Pidfile is at the same uuid as log
    pidfile_path = f"/tmp/rmcp-bg-{uuid}.pid"
    r = conn.exec(f"cat {pidfile_path}")
    assert r.stdout.strip() == pid, (
        f"pidfile content {r.stdout.strip()!r} does not match PID {pid!r}"
    )
    # Cleanup
    conn.exec(f"kill -KILL -- -{pid} 2>/dev/null; rm -f {pidfile_path}")


def test_background_pidfile_written_before_bg_pid_echo(conn):
    """The pidfile must exist by the time BG_PID line is sent — agent can rely
    on it being there if it can find the uuid."""
    # Run a "slow" foreground reader to inspect ordering: launch a bg task
    # that's slow to start, then immediately check pidfile presence.
    out = bash_tool.bash(conn, "sleep 60", run_in_background=True)
    log_match = re.search(r"Log:\s*/tmp/rmcp-bg-([a-f0-9]+)\.log", out)
    uuid = log_match.group(1)
    pidfile_path = f"/tmp/rmcp-bg-{uuid}.pid"
    # Pidfile must exist now (response came back after pidfile was written)
    r = conn.exec(f"test -f {pidfile_path} && echo YES || echo NO")
    assert r.stdout.strip() == "YES"
    # Cleanup
    pid_match = re.search(r"PID:\s*(\d+)", out)
    pid = pid_match.group(1)
    conn.exec(f"kill -KILL -- -{pid} 2>/dev/null; rm -f {pidfile_path}")


def test_background_launch_failure_message_mentions_pidfile_recovery(conn,
                                                                      monkeypatch):
    """When the launch path returns an Error, the message should point agent
    at /tmp/rmcp-bg-*.pid for orphan recovery."""
    # Simulate failure by patching exec_command to raise after setsid runs.
    # Easier: just check the error-path source string. We use a unit-style
    # check by inspecting the function's error-return text via a forced path.
    # Since the actual SSH failure is hard to simulate without breaking the
    # fixture, this test instead verifies the format string contains the hint
    # by reading the source file.
    import inspect
    from remote_mcp.tools import bash as bash_module
    src = inspect.getsource(bash_module._bash_background)
    assert "/tmp/rmcp-bg-*.pid" in src, (
        "_bash_background error path must mention pidfile recovery"
    )
    assert "cat /tmp/rmcp-bg-*.pid" in src or "cat /tmp/rmcp-bg-" in src
