"""D-group acceptance tests for JobArchive (spec §17 D)."""
import json
import os
import time

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.jobs.paths import (
    local_meta_path, local_archive_dir, local_zombie_dir,
)
from remote_mcp.tools.bash import bash
from remote_mcp.tools.jobs import jobs_tool
from remote_mcp.tools.job_kill import job_kill_tool
from remote_mcp.tools.job_archive import job_archive_tool


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
    cfg = HostConfig(
        name="jatest", hostname=sshd_container["host"],
        port=sshd_container["port"], user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    sid, _ = derive_sid()
    init_panel(sid, "jatest")
    yield c
    c.close()


def _id(name):
    sid, _ = derive_sid()
    from remote_mcp.jobs.meta import find_meta_by_name_anywhere
    m, _ = find_meta_by_name_anywhere(sid, "jatest", name)
    return m["id"] if m else None


def test_D1_archive_stopped(conn):
    bash(conn, "true", run_in_background=True, name="d1")
    time.sleep(1)
    jobs_tool(conn)  # refresh state
    id_ = _id("d1")  # capture before archive — meta is in active
    out = job_archive_tool(conn, name="d1")
    assert "Archived 'd1'" in out
    sid, _ = derive_sid()
    assert (local_archive_dir(sid, "jatest") / f"{id_}-meta.json").exists()


def test_D2_running_rejected(conn):
    bash(conn, "sleep 60", run_in_background=True, name="d2")
    jobs_tool(conn)
    out = job_archive_tool(conn, name="d2")
    assert "in state 'running'" in out


def test_D3_state_running_preset_rejected(conn):
    bash(conn, "sleep 60", run_in_background=True, name="d3")
    # No Jobs call between launch and archive
    out = job_archive_tool(conn, name="d3")
    assert "in state 'running'" in out


def test_D6_kill_failed_without_as_zombie(conn):
    """Use a task that refuses to die (same pattern as C4 in test_job_kill)."""
    bash(
        conn,
        'trap "" TERM; while true; do sleep 1; done',
        run_in_background=True, name="d6",
    )
    job_kill_tool(conn, name="d6")
    # state should be kill_failed now
    out = job_archive_tool(conn, name="d6")
    assert "state 'kill_failed'" in out
    assert "as_zombie=True" in out


def test_D7_kill_failed_with_as_zombie(conn):
    bash(
        conn,
        'trap "" TERM; while true; do sleep 1; done',
        run_in_background=True, name="d7",
    )
    job_kill_tool(conn, name="d7")
    id_ = _id("d7")  # capture before archive — meta is in active
    out = job_archive_tool(conn, name="d7", as_zombie=True)
    assert "Archived 'd7'" in out
    assert "ZOMBIE" in out
    sid, _ = derive_sid()
    assert (local_zombie_dir(sid, "jatest") / f"{id_}-meta.json").exists()


def test_D4_archive_then_reuse_name(conn):
    """D4 (spec §17 D4 + §11.5): After archive, name is released for reuse;
    new launch gets new id; old task queryable by old id."""
    # Launch + let stop + jobs refresh + archive
    bash(conn, "true", run_in_background=True, name="d4")
    time.sleep(1)
    jobs_tool(conn)
    old_id = _id("d4")
    out_a = job_archive_tool(conn, name="d4")
    assert "Archived 'd4'" in out_a

    # Now re-launch with same name — must succeed
    out_b = bash(conn, "sleep 60", run_in_background=True, name="d4")
    assert "Started background task" in out_b
    new_id = _id("d4")
    assert new_id != old_id, f"expected new id != old {old_id}, got {new_id}"

    # Old task still queryable
    out_q = jobs_tool(conn, id=old_id)
    assert '"name": "d4"' in out_q
    assert '"archived_at"' in out_q


def test_D5_remote_files_survive_archive(conn):
    """D5 (spec §17 D5): pid file and log file on remote remain after archive."""
    bash(conn, "true", run_in_background=True, name="d5", log_path="/tmp/d5-log")
    time.sleep(1)
    jobs_tool(conn)
    sid, _ = derive_sid()
    id_ = _id("d5")
    # Archive
    job_archive_tool(conn, name="d5")
    # Verify remote files still exist via SFTP
    sftp = conn.get_sftp()
    # pid file: remote_pid_path returns ~/..., strip ~/ for SFTP
    from remote_mcp.jobs.paths import remote_pid_path
    pid_remote = remote_pid_path(sid, id_)
    sftp_pid_path = pid_remote[2:] if pid_remote.startswith("~/") else pid_remote
    sftp.stat(sftp_pid_path)  # should not raise
    # log file: absolute path, SFTP handles it directly
    sftp.stat("/tmp/d5-log")  # should not raise


def test_D8_five_zombies_trigger_escalation(conn):
    """D8 (spec §17 D8 + §11.3): JobArchive(as_zombie=True) on the 5th zombie
    triggers escalation warning. The first 4 do NOT trigger it."""
    for i in range(5):
        name = f"d8-zombie-{i}"
        # Launch a task that traps TERM (so it ends up kill_failed)
        bash(
            conn,
            'trap "" TERM; while true; do sleep 1; done',
            run_in_background=True, name=name,
        )
        # Issue kill — should fail
        job_kill_tool(conn, name=name)
        # Archive as zombie
        out = job_archive_tool(conn, name=name, as_zombie=True)
        assert "as ZOMBIE" in out
        if i < 4:
            # First 4: no escalation
            assert "ESCALATION WARNING" not in out, (
                f"zombie #{i+1}: should NOT trigger escalation, got: {out!r}"
            )
        else:
            # 5th: escalation triggers
            assert "ESCALATION WARNING" in out
            assert "is now 5" in out
            assert ">= threshold" in out

    # Cleanup: force-kill all surviving processes
    sid, _ = derive_sid()
    from remote_mcp.jobs.meta import find_meta_by_name_anywhere
    from remote_mcp.connection import exec_with_snapshot
    for i in range(5):
        name = f"d8-zombie-{i}"
        m, _ = find_meta_by_name_anywhere(sid, "jatest", name)
        if m and m.get("pid"):
            exec_with_snapshot(
                conn,
                f"kill -KILL -- -{m['pid']} 2>/dev/null || true",
                timeout=5,
            )


def test_D9_stopped_with_as_zombie_rejected(conn):
    bash(conn, "true", run_in_background=True, name="d9")
    time.sleep(1)
    jobs_tool(conn)
    out = job_archive_tool(conn, name="d9", as_zombie=True)
    assert "as_zombie=True requires state=kill_failed" in out


def test_D10_no_remote_ssh_calls(conn, monkeypatch):
    """Verify JobArchive doesn't call exec_with_snapshot."""
    bash(conn, "true", run_in_background=True, name="d10")
    time.sleep(1)
    jobs_tool(conn)
    from remote_mcp.tools import job_archive
    # job_archive shouldn't even import exec_with_snapshot; if it does, fail
    assert "exec_with_snapshot" not in job_archive.__dict__
    out = job_archive_tool(conn, name="d10")
    assert "Archived 'd10'" in out
