"""v0.3.0: background bash PID confirmation + SFTP fallback. Updated from v0.2.2."""
import re
import time

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.tools import bash as bash_tool


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield tmp_path


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
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
    sid, _ = derive_sid()
    init_panel(sid, "test")
    yield c
    c.close()


def test_background_launch_writes_pidfile(conn):
    """After a successful background launch, the remote pid file exists and
    contains the PID. v0.3.0: pid file at ~/.cache/remote-mcp-<sid>-<id>-pid."""
    sid, _ = derive_sid()
    out = bash_tool.bash(conn, "sleep 30", run_in_background=True)
    # v0.3.0 structured return: pid and id fields
    pid_match = re.search(r"pid: (\d+)", out)
    id_match = re.search(r"id: (\d+)", out)
    assert pid_match and id_match, f"could not parse pid/id from: {out!r}"
    pid = pid_match.group(1)
    id_ = id_match.group(1)
    # Pidfile is at ~/.cache/remote-mcp-<sid>-<id>-pid
    pidfile_path = f"~/.cache/remote-mcp-{sid}-{id_}-pid"
    r = conn.exec(f"cat {pidfile_path}")
    assert r.stdout.strip() == pid, (
        f"pidfile content {r.stdout.strip()!r} does not match PID {pid!r}"
    )
    # Cleanup
    conn.exec(f"kill -KILL -- -{pid} 2>/dev/null; true")


def test_background_pidfile_written_before_bg_pid_echo(conn):
    """The pidfile must exist by the time BG_PID line is sent — agent can rely
    on it being there if it can find the id."""
    sid, _ = derive_sid()
    out = bash_tool.bash(conn, "sleep 60", run_in_background=True)
    id_match = re.search(r"id: (\d+)", out)
    id_ = id_match.group(1)
    pidfile_path = f"~/.cache/remote-mcp-{sid}-{id_}-pid"
    # Pidfile must exist now (response came back after pidfile was written)
    r = conn.exec(f"test -f {pidfile_path} && echo YES || echo NO")
    assert r.stdout.strip() == "YES"
    # Cleanup
    pid_match = re.search(r"pid: (\d+)", out)
    pid = pid_match.group(1)
    conn.exec(f"kill -KILL -- -{pid} 2>/dev/null; true")


def test_background_launch_failure_message_mentions_sftp_recovery(conn, monkeypatch):
    """v0.3.0: when launch fails (both exec and SFTP fallback fail), the error
    message should point agent at the remote pid file for orphan recovery."""
    from remote_mcp.tools import bash as bash_mod
    real_exec = bash_mod.exec_with_snapshot
    call_count = [0]

    def _fake(conn_arg, command, timeout):
        call_count[0] += 1
        if call_count[0] == 1:  # mkdir
            return real_exec(conn_arg, command, timeout)
        from remote_mcp.connection import ExecResult
        return ExecResult(stdout="", stderr="", exit_code=0, timed_out=False, elapsed_sec=0.1)

    monkeypatch.setattr(bash_mod, "exec_with_snapshot", _fake)
    # Also patch SFTP fallback to simulate "file not found"
    monkeypatch.setattr(bash_mod, "_bg_sftp_fallback",
                        lambda *a: (None, None, None, False, "simulated SFTP failure"))

    out = bash_tool.bash(conn, "sleep 1", run_in_background=True)
    assert "could not be confirmed" in out
    assert "The task has NOT been added to the panel" in out
    # v0.3.0: error message mentions the remote pid path for orphan recovery
    assert "~/.cache/remote-mcp-" in out and "-pid" in out
