"""B-group acceptance tests for Jobs (spec §17 B)."""
import json
import re
import time

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.paths import local_meta_path
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.tools.bash import bash
from remote_mcp.tools.jobs import jobs_tool


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield tmp_path


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
    cfg = HostConfig(
        name="jbgtest",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    sid, _ = derive_sid()
    init_panel(sid, "jbgtest")
    yield c
    c.close()


def test_B1_empty(conn):
    out = jobs_tool(conn)
    assert "0 active jobs" in out


def test_B2_one_running_task(conn):
    bash(conn, "sleep 60", run_in_background=True, name="b2")
    out = jobs_tool(conn)
    assert "b2" in out
    assert "running" in out


def test_B3_task_stops(conn):
    bash(conn, "true", run_in_background=True, name="b3")
    time.sleep(1)
    out = jobs_tool(conn)
    assert "b3" in out
    assert "stopped" in out


def test_B4_single_mode_detail(conn):
    bash(conn, "sleep 60", run_in_background=True, name="b4")
    out = jobs_tool(conn, name="b4")
    assert "command" in out
    assert "kill_attempts" in out
    assert "status_script_output" in out


def test_B5_filter_stopped_unprocessed(conn):
    bash(conn, "sleep 60", run_in_background=True, name="alive5")
    bash(conn, "true", run_in_background=True, name="dead5")
    time.sleep(1)
    # Call Jobs once to refresh state before filtering
    jobs_tool(conn)
    out = jobs_tool(conn, filter="stopped_unprocessed")
    assert "dead5" in out
    assert "alive5" not in out


def test_B6_not_found(conn):
    out = jobs_tool(conn, name="nope")
    assert "Error: no job with name='nope'" in out


def test_B7_name_and_id(conn):
    out = jobs_tool(conn, name="x", id=1)
    assert "Error: provide only one of name or id" in out


def test_B8_filter_with_name(conn):
    out = jobs_tool(conn, name="x", filter="zombies")
    assert "Error: filter is for list mode" in out
