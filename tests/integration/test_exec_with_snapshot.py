"""Integration tests for the exec_with_snapshot helper (spec §19)."""
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection, exec_with_snapshot, ExecResult


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="testhost",
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


def test_exec_with_snapshot_happy(conn):
    r = exec_with_snapshot(conn, "echo hello", timeout=10.0)
    assert isinstance(r, ExecResult)
    assert r.exit_code == 0
    assert r.stdout.strip() == "hello"
    assert r.stderr == ""
    assert r.timed_out is False
    assert r.elapsed_sec >= 0


def test_exec_with_snapshot_non_zero_exit(conn):
    r = exec_with_snapshot(conn, "exit 7", timeout=10.0)
    assert r.exit_code == 7
    assert r.timed_out is False


def test_exec_with_snapshot_stderr_captured_separately(conn):
    r = exec_with_snapshot(
        conn, "echo out; echo err >&2; exit 0", timeout=10.0
    )
    assert r.stdout.strip() == "out"
    assert r.stderr.strip() == "err"


def test_exec_with_snapshot_timeout(conn):
    r = exec_with_snapshot(conn, "sleep 10", timeout=1.0)
    assert r.timed_out is True
    assert r.exit_code == -1
    # After timeout, channel was closed; subsequent calls on same conn should work
    r2 = exec_with_snapshot(conn, "echo recovered", timeout=5.0)
    assert r2.exit_code == 0
    assert r2.stdout.strip() == "recovered"


def test_exec_with_snapshot_stdin_closed(conn):
    """Commands that read stdin should not hang (</dev/null in wrap)."""
    r = exec_with_snapshot(conn, "cat", timeout=3.0)
    assert r.timed_out is False
    assert r.exit_code == 0
