import socket
import threading
import time as time_module

import paramiko
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
    c._capture_snapshot()  # B2: server startup calls this; tests must too
    yield c
    c.close()


def test_bash_foreground_echo(conn):
    out = bash_tool.bash(conn, "echo hi")
    # No prefix anymore — suffix is added by server.py (Stage C)
    assert out.strip() == "hi"


def test_bash_foreground_does_not_persist_cwd(conn):
    # cd inside one call must not affect the next call (spec §5.2)
    pwd_before = bash_tool.bash(conn, "pwd").strip().splitlines()[-1]
    bash_tool.bash(conn, "cd /tmp")
    pwd_after = bash_tool.bash(conn, "pwd").strip().splitlines()[-1]
    assert pwd_after == pwd_before, (
        f"cwd persisted: before={pwd_before!r}, after={pwd_after!r}"
    )


def test_bash_foreground_does_not_persist_env(conn):
    bash_tool.bash(conn, "export RMCP_TEST_VAR=hello")
    out = bash_tool.bash(conn, "echo \"VAR=$RMCP_TEST_VAR\"")
    assert "VAR=" in out
    assert "VAR=hello" not in out  # var should be empty


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
    # Error message format: "Error: Command timed out after Ns on <host>"
    assert "Error: Command timed out after 2" in out
    assert "on test" in out


def test_bash_foreground_timeout_preserves_partial_output(conn):
    out = bash_tool.bash(conn, "echo START; sleep 100", timeout=2)
    # Spec §5.4: partial output must survive timeout
    assert "START" in out
    assert "Error: Command timed out" in out


def test_bash_foreground_stdin_is_devnull(conn):
    # `cat` with no args reads stdin → without /dev/null it would hang forever
    out = bash_tool.bash(conn, "cat", timeout=5)
    # Should return immediately (EOF on stdin)
    assert "Error: Command timed out" not in out


def test_bash_foreground_snapshot_loads_path(conn):
    # snapshot includes user PATH, so `which bash` should find a path that
    # at minimum is non-empty
    out = bash_tool.bash(conn, "which bash")
    assert "/bash" in out


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
    """Extract the last integer from bash tool output."""
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


def test_bash_background_does_not_use_persistent_session(conn):
    # No persistent state — the connection has no _bash_session attr at all.
    assert not hasattr(conn, "_bash_session")
    bash_tool.bash(conn, "sleep 1", run_in_background=True)
    assert not hasattr(conn, "_bash_session")


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


@pytest.fixture
def conn_with_cwd(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        bash_timeout_default=15,
        cwd="/tmp",
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()  # B2: server startup calls this; tests must too
    yield c
    c.close()


def test_bash_pwd_uses_configured_cwd(conn_with_cwd):
    out = bash_tool.bash(conn_with_cwd, "pwd")
    assert out.strip() == "/tmp"


def test_bash_cd_does_not_persist_cwd_resets_to_configured(conn_with_cwd):
    bash_tool.bash(conn_with_cwd, "cd /var")
    out = bash_tool.bash(conn_with_cwd, "pwd")
    assert out.strip() == "/tmp"  # not /var


def test_bash_background_uses_configured_cwd(conn_with_cwd):
    """Background bash should start at the configured cwd, not at $HOME.
    Without sourcing the snapshot, background runs at sshd default which
    silently breaks users who set --cwd."""
    out = bash_tool.bash(conn_with_cwd, "pwd > /tmp/rmcp-bg-cwd-test.out", run_in_background=True)
    m = re.search(r"PID:\s*(\d+)", out)
    assert m, f"no PID in output: {out}"
    pid = m.group(1)

    # Wait for the background process to finish (it's a quick pwd)
    for _ in range(50):
        check = bash_tool.bash(conn_with_cwd, f"kill -0 {pid} 2>/dev/null && echo running || echo done")
        if "done" in check:
            break
        time.sleep(0.1)

    # Read the captured pwd
    result = bash_tool.bash(conn_with_cwd, "cat /tmp/rmcp-bg-cwd-test.out")
    assert "/tmp" in result, f"background bash didn't start at configured cwd /tmp, got: {result!r}"
    bash_tool.bash(conn_with_cwd, "rm -f /tmp/rmcp-bg-cwd-test.out")


def test_bash_foreground_surfaces_channel_death_promptly(conn, sshd_kill_and_restart):
    """v0.2.1 fix: when the transport dies mid-call, bash must surface that
    clearly (not return an opaque "[Exit code: -1]" that hides the cause).

    Behavior verified:
    - Returns within a couple seconds (no waiting out bash_timeout_default)
    - Return value starts with "Error: SSH channel to <host> closed unexpectedly"
      so the agent can distinguish channel death from a real command failure
    - Does NOT auto-retry (re-running non-idempotent commands silently would
      be worse than surfacing the failure — agent decides what to do)
    """
    # `conn` fixture has bash_timeout_default=15. Call must finish well before.
    result_box: dict = {}

    def run():
        result_box["ret"] = bash_tool.bash(conn, "sleep 30", timeout=15)

    t = threading.Thread(target=run)
    start = time_module.monotonic()
    t.start()
    time_module.sleep(1.0)  # let exec_command + drain loop establish
    sshd_kill_and_restart(conn)  # kill the transport
    t.join(timeout=14.0)
    elapsed = time_module.monotonic() - start

    assert not t.is_alive(), (
        f"bash() hung past socket kill (>{elapsed:.1f}s) — channel-death "
        f"was not surfaced"
    )
    assert elapsed < 8.0, (
        f"bash() took {elapsed:.2f}s to react to socket death — should "
        f"react within a couple seconds"
    )

    ret = result_box.get("ret", "")
    assert ret.startswith("Error: SSH channel to test closed unexpectedly"), (
        f"expected explicit channel-death error, got: {ret!r}"
    )

    if "ret" in result_box:
        # Function returned a string rather than raising. Acceptable IF it's
        # not the misleading "Command timed out" (which would mean the bug
        # is unfixed). The function may also return cleanly if the channel
        # happened to deliver an exit status before the kill took effect.
        ret = result_box["ret"]
        assert "Command timed out" not in ret, (
            f"bash returned timeout error instead of propagating channel "
            f"death — drain loop is still swallowing recv exceptions. "
            f"Got: {ret!r}"
        )
    else:
        # Exception path — the fix surfaces the channel death
        assert "exc_type" in result_box, (
            f"thread finished but neither returned nor raised an "
            f"expected exception: {result_box!r}"
        )
