"""A-group acceptance tests for Bash extension (spec §17 A)."""
import re
import time
from pathlib import Path

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.paths import local_meta_path, local_sid_host_dir
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.tools.bash import bash


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield tmp_path


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
    cfg = HostConfig(
        name="bgtest",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    sid, _ = derive_sid()
    init_panel(sid, "bgtest")
    yield c
    c.close()


def test_A1_default_params_returns_structured_fields(conn):
    out = bash(conn, "sleep 100", run_in_background=True)
    assert "Started background task." in out
    assert re.search(r"id: \d+", out)
    assert re.search(r"name: bg-[0-9a-f]{12}", out)
    assert re.search(r"log_path: /.+/.cache/remote-mcp-[0-9a-f]{12}-\d+\.log", out)
    assert re.search(r"pid: \d+", out)
    assert re.search(r"started_at: \d{4}-\d{2}-\d{2}T", out)


def test_A2_custom_name_and_log_path(conn):
    out = bash(
        conn, "sleep 100",
        run_in_background=True,
        name="myjob",
        log_path="/tmp/myjob.log",
        description="A2 test",
    )
    assert "name: myjob" in out
    assert "log_path: /tmp/myjob.log" in out
    check = bash(conn, "ls /tmp/myjob.log", run_in_background=False, timeout=5)
    assert "/tmp/myjob.log" in check


def test_A3_name_collision_rejected(conn):
    bash(conn, "sleep 100", run_in_background=True, name="dup")
    out2 = bash(conn, "sleep 1", run_in_background=True, name="dup")
    assert "Error: job name 'dup' already in active panel" in out2


def test_A4_log_path_parent_recursively_created(conn):
    out = bash(
        conn, "sleep 60",
        run_in_background=True,
        log_path="/tmp/rmcp-test-A4/sub/dir/log",
    )
    assert "Started background task" in out
    # Verify on remote
    check = bash(conn, "ls /tmp/rmcp-test-A4/sub/dir/log", run_in_background=False, timeout=5)
    assert "log" in check


def test_A5_log_path_parent_is_file(conn):
    out = bash(
        conn, "sleep 60",
        run_in_background=True,
        log_path="/etc/passwd/log",
    )
    assert "Error: log_path parent" in out
    assert "not a directory" in out


def test_A6_local_meta_state_running_after_launch(conn, panel):
    sid, _ = derive_sid()
    out = bash(conn, "sleep 100", run_in_background=True, name="a6")
    m = re.search(r"id: (\d+)", out)
    assert m
    id_ = int(m.group(1))
    meta_path = local_meta_path(sid, "bgtest", id_)
    assert meta_path.exists()
    import json
    meta = json.loads(meta_path.read_text())
    assert meta["pid"] > 0
    assert meta["state"] == "running"
    assert not meta["log_path"].startswith("~/"), "log_path must be expanded to absolute per spec §5.3.2 step 4"


def test_A7_response_lost_sftp_fallback_succeeds(conn, panel, monkeypatch):
    """Spec §17 A7: simulate wrap echo lost; pid file written; SFTP fallback recovers."""
    from remote_mcp.tools import bash as bash_mod
    real_exec = bash_mod.exec_with_snapshot
    call_count = [0]
    def _fake(conn_arg, command, timeout):
        # Pass through mkdir; mangle wrap response (drop echoes)
        call_count[0] += 1
        if call_count[0] == 1:  # mkdir
            return real_exec(conn_arg, command, timeout)
        # 2nd call is the wrap — actually run it but blank the result so parser fails
        real_exec(conn_arg, command, timeout)
        from remote_mcp.connection import ExecResult
        return ExecResult(stdout="", stderr="", exit_code=0, timed_out=False, elapsed_sec=0.1)
    monkeypatch.setattr(bash_mod, "exec_with_snapshot", _fake)
    out = bash(conn, "sleep 60", run_in_background=True, name="a7")
    assert "Started background task" in out
    assert "NOTE: started_at is approximated" in out
    # pid recovered
    assert re.search(r"pid: \d+", out)


def test_A8_response_lost_sftp_fallback_fails(conn, panel, monkeypatch):
    """Spec §17 A8: simulate wrap never wrote pid; fallback fails; task NOT in panel."""
    from remote_mcp.tools import bash as bash_mod
    real_exec = bash_mod.exec_with_snapshot
    call_count = [0]
    def _fake(conn_arg, command, timeout):
        call_count[0] += 1
        if call_count[0] == 1:  # mkdir
            return real_exec(conn_arg, command, timeout)
        # 2nd: SKIP the wrap entirely (no pid file written), return empty
        from remote_mcp.connection import ExecResult
        return ExecResult(stdout="", stderr="", exit_code=0, timed_out=False, elapsed_sec=0.1)
    monkeypatch.setattr(bash_mod, "exec_with_snapshot", _fake)
    # Also patch SFTP fallback to simulate "file not found" (previous tests may have
    # left remote pid files for the same sid+id, since remote is shared across tests)
    def _failing_sftp_fallback(conn_arg, sid, id_):
        return None, None, None, False, "simulated SFTP failure"
    monkeypatch.setattr(bash_mod, "_bg_sftp_fallback", _failing_sftp_fallback)
    out = bash(conn, "sleep 60", run_in_background=True, name="a8")
    assert "could not be confirmed" in out
    assert "The task has NOT been added to the panel" in out
    # local meta absent
    sid, _ = derive_sid()
    sid_host = local_sid_host_dir(sid, "bgtest")
    # No leftover <id>-meta.json (alloc'd id is some int; verify dir scan finds no a8)
    for child in sid_host.glob("*-meta.json"):
        import json
        m = json.loads(child.read_text())
        assert m["name"] != "a8"
