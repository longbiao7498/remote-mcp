"""C-group acceptance tests for JobKill (spec §17 C)."""
import pytest
import time

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.tools.bash import bash
from remote_mcp.tools.jobs import jobs_tool
from remote_mcp.tools.job_kill import job_kill_tool


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
    cfg = HostConfig(
        name="jktest", hostname=sshd_container["host"],
        port=sshd_container["port"], user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    sid, _ = derive_sid()
    init_panel(sid, "jktest")
    yield c
    c.close()


def test_C1_default_kill_succeeds(conn):
    bash(conn, "sleep 60", run_in_background=True, name="c1")
    out = job_kill_tool(conn, name="c1")
    assert "Kill requested for 'c1'" in out
    assert "kill_command: kill -TERM" in out
    assert "state_now: killed" in out


def test_C2_archived_kill_rejected(conn):
    bash(conn, "true", run_in_background=True, name="c2")
    time.sleep(0.5)
    # Need to archive — but JobArchive is later stage; mock by calling meta directly
    sid, _ = derive_sid()
    from remote_mcp.jobs.meta import (
        find_meta_by_name_anywhere, write_meta, move_to_archive,
    )
    m, _ = find_meta_by_name_anywhere(sid, "jktest", "c2")
    m["archived_at"] = "now"
    m["archived_at_unix"] = int(time.time())
    write_meta(sid, "jktest", m)
    move_to_archive(sid, "jktest", m["id"])
    out = job_kill_tool(conn, name="c2")
    assert "cannot kill job 'c2'" in out


def test_C3_custom_kill_cmd(conn):
    bash(conn, "sleep 60", run_in_background=True, name="c3")
    out = job_kill_tool(conn, name="c3", kill_cmd="echo would scancel")
    assert "kill_command: echo would scancel" in out


def test_C4_three_kill_failures_triggers_L1(conn):
    bash(
        conn,
        'trap "" TERM; while true; do sleep 1; done',
        run_in_background=True, name="c4",
    )
    job_kill_tool(conn, name="c4")
    job_kill_tool(conn, name="c4")
    out = job_kill_tool(conn, name="c4")
    assert "NOTE: this task has 3 failed kill attempts now" in out


def test_C5_five_stuck_tasks_trigger_L2(conn):
    """Five unkillable tasks — 5th task's 3rd kill triggers L1 + L2."""
    names = [f"c5_{i}" for i in range(5)]
    for n in names:
        bash(
            conn,
            'trap "" TERM; while true; do sleep 1; done',
            run_in_background=True, name=n,
        )
    # Kill each task 2 times (no L1 yet)
    for n in names:
        job_kill_tool(conn, name=n)
        job_kill_tool(conn, name=n)
    # 3rd kill on each — by the 5th task's 3rd kill we should have L1 + L2
    for n in names[:-1]:
        job_kill_tool(conn, name=n)
    out = job_kill_tool(conn, name=names[-1])
    assert "NOTE: this task has 3 failed kill attempts now" in out
    assert "WARNING:" in out
    assert "persistent kill failures" in out
