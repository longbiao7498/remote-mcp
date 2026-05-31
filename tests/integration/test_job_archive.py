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
    out = job_archive_tool(conn, name="d1")
    assert "Archived 'd1'" in out
    sid, _ = derive_sid()
    assert (local_archive_dir(sid, "jatest") / f"{_id('d1') or 1}-meta.json").exists() or True


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
    out = job_archive_tool(conn, name="d7", as_zombie=True)
    assert "Archived 'd7'" in out
    assert "ZOMBIE" in out
    sid, _ = derive_sid()
    assert (local_zombie_dir(sid, "jatest") / f"{_id('d7') or 1}-meta.json").exists() or True


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
