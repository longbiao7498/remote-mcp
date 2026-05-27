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
        bash_timeout_default=15,
    )
    c = SSHConnection(cfg)
    c.connect()
    yield c
    c.close()


def test_bash_foreground_echo(conn):
    out = bash_tool.bash(conn, "echo hi")
    assert "[host=test cwd=" in out
    assert "hi" in out


def test_bash_foreground_persists_cwd(conn):
    bash_tool.bash(conn, "cd /tmp")
    out = bash_tool.bash(conn, "pwd")
    assert "cwd=/tmp" in out
    assert "/tmp" in out


def test_bash_foreground_nonzero_exit(conn):
    out = bash_tool.bash(conn, "false")
    assert "[Exit code: 1]" in out


def test_bash_foreground_output_cap(conn):
    conn.config.bash_output_cap = 200
    out = bash_tool.bash(conn, "yes hello | head -1000")
    # Total length should be bounded by cap + truncation message
    assert "[truncated to" in out


def test_bash_foreground_timeout(conn):
    out = bash_tool.bash(conn, "sleep 100", timeout=2)
    assert out.startswith("Error: Command timed out")
    assert "on test" in out


import re
import time


def test_bash_background_returns_pid_and_log(conn):
    out = bash_tool.bash(conn, "sleep 30", run_in_background=True)
    assert "Started background task" in out
    assert re.search(r"PID:\s*\d+", out)
    assert re.search(r"Log:\s*/tmp/rmcp-bg-[a-f0-9]+\.log", out)
    # Cleanup
    m = re.search(r"PID:\s*(\d+)", out)
    pid = m.group(1)
    bash_tool.bash(conn, f"kill -KILL -- -{pid} 2>/dev/null; true")


def test_bash_background_kill_via_process_group(conn):
    out = bash_tool.bash(conn, "sleep 100", run_in_background=True)
    m = re.search(r"PID:\s*(\d+)", out)
    pid = m.group(1)

    # Verify alive
    alive = bash_tool.bash(conn, f"kill -0 {pid} && echo running || echo done")
    assert "running" in alive

    # Kill the whole group
    bash_tool.bash(conn, f"kill -TERM -- -{pid}")
    time.sleep(1.5)

    dead = bash_tool.bash(conn, f"kill -0 {pid} 2>/dev/null && echo running || echo done")
    assert "done" in dead


def _parse_last_int(bash_output: str) -> int:
    """Extract the last integer from bash tool output (skipping the [host=...] prefix line)."""
    # bash tool output always starts with '[host=... cwd=...]\n'; skip it
    lines = bash_output.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if re.fullmatch(r"\d+", line):
            return int(line)
    raise ValueError(f"No integer found in output: {bash_output!r}")


def test_bash_background_kills_children_via_group(conn):
    """Verify -PGID kill takes down spawned children."""
    cmd = "( sleep 200 & sleep 300 & wait )"
    out = bash_tool.bash(conn, cmd, run_in_background=True)
    m = re.search(r"PID:\s*(\d+)", out)
    pid = m.group(1)
    time.sleep(0.5)

    # Check processes in the process group (setsid makes PID==PGID, so ps -g <pid> works)
    # ps -g lists all members of the process group; skip header, count lines
    pg_before = bash_tool.bash(conn, f"ps -g {pid} --no-headers 2>/dev/null | wc -l || echo 0")
    n = _parse_last_int(pg_before)
    # Expect at least 3: setsid bash, inner bash wrapper, sleep 200, sleep 300
    assert n >= 3, f"Expected >=3 processes in group, got {n}: {pg_before}"

    bash_tool.bash(conn, f"kill -KILL -- -{pid}")
    time.sleep(1.5)

    pg_after = bash_tool.bash(conn, f"ps -g {pid} --no-headers 2>/dev/null | wc -l || echo 0")
    n_after = _parse_last_int(pg_after)
    assert n_after == 0, f"Expected 0 processes in group after kill, got {n_after}: {pg_after}"


def test_bash_background_log_readable(conn):
    out = bash_tool.bash(
        conn, "for i in 1 2 3; do echo line$i; sleep 0.1; done",
        run_in_background=True,
    )
    log_match = re.search(r"Log:\s*(/tmp/rmcp-bg-[a-f0-9]+\.log)", out)
    log_path = log_match.group(1)
    time.sleep(1.5)
    # Read the log via Bash cat
    log_content = bash_tool.bash(conn, f"cat {log_path}")
    assert "line1" in log_content
    assert "line2" in log_content
    assert "line3" in log_content
