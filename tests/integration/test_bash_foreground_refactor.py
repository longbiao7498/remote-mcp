"""Verify _bash_foreground behavior is unchanged after refactor to use
exec_with_snapshot (Stage B2)."""
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools.bash import bash


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


def test_bash_foreground_returns_stdout_only(conn):
    out = bash(conn, "echo hello", run_in_background=False, timeout=10.0)
    assert out.strip() == "hello"


def test_bash_foreground_concatenates_stdout_then_stderr(conn):
    """v0.3.0 behavior: stdout drained first, stderr appended after.
    Differs from v0.2.x interleaved order — see exec_with_snapshot docstring."""
    out = bash(
        conn, "echo out1; echo err1 >&2; echo out2; echo err2 >&2; exit 0",
        run_in_background=False, timeout=10.0,
    )
    # Both streams present
    assert "out1" in out
    assert "out2" in out
    assert "err1" in out
    assert "err2" in out
    # stdout content precedes stderr content (concatenated, not interleaved)
    stdout_end = max(out.rfind("out1"), out.rfind("out2"))
    stderr_start = min(out.find("err1"), out.find("err2"))
    assert stdout_end < stderr_start, (
        f"Expected stdout to precede stderr in output, got: {out!r}"
    )


def test_bash_foreground_exit_code_suffix(conn):
    out = bash(conn, "exit 3", run_in_background=False, timeout=10.0)
    assert "[Exit code: 3]" in out


def test_bash_foreground_timeout(conn):
    out = bash(conn, "sleep 10", run_in_background=False, timeout=1.0)
    assert "Error: Command timed out" in out


def test_bash_foreground_stdin_closed(conn):
    out = bash(conn, "cat", run_in_background=False, timeout=3.0)
    # cat </dev/null returns immediately with empty output
    assert "Error:" not in out


def test_bash_foreground_caps_at_output_cap(conn):
    """Output cap (bash_output_cap=100KB) still enforced after refactor."""
    out = bash(
        conn, "yes hello | head -100000",
        run_in_background=False, timeout=10.0,
    )
    # bash_output_cap default 100KB; truncation marker should appear
    assert len(out) < 110_000
    assert "truncated" in out
