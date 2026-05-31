"""E-group acceptance tests for JobScript (spec §17 E)."""
import pytest
import time

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.jobs.paths import local_status_path
from remote_mcp.tools.bash import bash
from remote_mcp.tools.jobs import jobs_tool
from remote_mcp.tools.job_script import job_script_tool


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
    cfg = HostConfig(
        name="jstest", hostname=sshd_container["host"],
        port=sshd_container["port"], user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    sid, _ = derive_sid()
    init_panel(sid, "jstest")
    yield c
    c.close()


def test_E1_set_success(conn):
    bash(conn, "sleep 60", run_in_background=True, name="e1")
    out = job_script_tool(conn, name="e1", script="echo hello", timeout=5)
    assert "Status script attached to 'e1'" in out
    assert "exit_code: 0" in out
    assert "hello" in out


def test_E2_subsequent_jobs_call_runs_script(conn):
    bash(conn, "sleep 60", run_in_background=True, name="e2")
    job_script_tool(conn, name="e2", script="echo hi-from-script", timeout=5)
    out = jobs_tool(conn, name="e2")
    assert "hi-from-script" in out


def test_E3_first_run_timeout_rejects(conn):
    bash(conn, "sleep 60", run_in_background=True, name="e3")
    out = job_script_tool(conn, name="e3", script="sleep 30", timeout=2)
    assert "Error: status script first-run timed out after 2s" in out
    out2 = jobs_tool(conn, name="e3")
    assert '"status_script_output": null' in out2


def test_E4_nonzero_exit_accepted_with_note(conn):
    bash(conn, "sleep 60", run_in_background=True, name="e4")
    out = job_script_tool(conn, name="e4", script="exit 2", timeout=5)
    assert "Status script attached to 'e4'" in out
    assert "NOTE: first-run exited with non-zero code" in out
    assert "exit_code: 2" in out


def test_E5_clear_deletes_local_only(conn):
    bash(conn, "sleep 60", run_in_background=True, name="e5")
    job_script_tool(conn, name="e5", script="echo x", timeout=5)
    sid, _ = derive_sid()
    assert local_status_path(sid, "jstest", _id_of(conn, "e5")).exists()
    out = job_script_tool(conn, name="e5", script="", timeout=5)
    assert "Status script cleared" in out
    assert not local_status_path(sid, "jstest", _id_of(conn, "e5")).exists()
    sftp = conn.get_sftp()
    # Remote cache should still be there (per spec §9.2.2)
    sftp.stat(f".cache/remote-mcp-{sid}-{_id_of(conn, 'e5')}-status.sh")  # should not raise


def test_E7_cache_miss_reuploads_from_local(conn):
    bash(conn, "sleep 60", run_in_background=True, name="e7")
    job_script_tool(conn, name="e7", script="echo persists", timeout=5)
    # Remove remote cache
    sid, _ = derive_sid()
    sftp = conn.get_sftp()
    sftp.remove(f".cache/remote-mcp-{sid}-{_id_of(conn, 'e7')}-status.sh")
    out = jobs_tool(conn, name="e7")
    assert "persists" in out


def test_E8_timeout_in_replace_scenario_clears_meta(conn):
    """Replacing an existing script with one that times out must reset meta.script_timeout
    to None so subsequent Jobs calls don't try to run the deleted script (spec §9.2.1 + §14 C6)."""
    import json
    from remote_mcp.jobs.paths import local_meta_path

    bash(conn, "sleep 60", run_in_background=True, name="e8")
    # First attach a valid script
    job_script_tool(conn, name="e8", script="echo first", timeout=5)
    sid, _ = derive_sid()
    id_ = _id_of(conn, "e8")
    # Verify meta has script_timeout=5
    meta = json.loads(local_meta_path(sid, "jstest", id_).read_text())
    assert meta["script_timeout"] == 5
    # Now replace with a script that times out
    out = job_script_tool(conn, name="e8", script="sleep 30", timeout=2)
    assert "Error: status script first-run timed out" in out
    # Verify meta.script_timeout is back to None
    meta = json.loads(local_meta_path(sid, "jstest", id_).read_text())
    assert meta["script_timeout"] is None, (
        f"After timeout-rejection, script_timeout should be None but is {meta['script_timeout']}"
    )
    # Jobs(name='e8') should now NOT try to run any script
    out2 = jobs_tool(conn, name="e8")
    assert '"status_script_output": null' in out2


def _id_of(conn, job_name):
    """Look up id given name."""
    sid, _ = derive_sid()
    from remote_mcp.jobs.meta import find_meta_by_name_anywhere
    m, _ = find_meta_by_name_anywhere(sid, conn.config.name, job_name)
    return m["id"]
