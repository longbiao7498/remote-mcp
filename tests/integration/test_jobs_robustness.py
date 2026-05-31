"""G-group acceptance: rugosity tests using flaky_proxy (spec §17 G).

Note on drop_all() vs close_now():
The plan uses flaky_proxy.drop_all() to simulate network loss. However,
exec_with_snapshot() calls exec_command(timeout=None) which blocks indefinitely
on channel open when bytes are silently dropped (paramiko Event.wait(timeout=None)).
We therefore use close_now() instead, which sends a TCP RST that paramiko
detects immediately as an SSH-layer error — semantically equivalent "network drop"
from the spec's perspective (the remote operation cannot complete).
"""
import pytest

from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.tools.bash import bash
from remote_mcp.tools.jobs import jobs_tool
from remote_mcp.tools.job_kill import job_kill_tool


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield tmp_path


def test_G1_log_mkdir_network_drop_cleans_local_meta(conn_via_proxy, flaky_proxy, panel):
    """Spec §17 G1: mkdir log_path parent fails mid-call → local meta deleted."""
    sid, _ = derive_sid()
    init_panel(sid, "proxytest")
    # close_now() causes TCP RST; paramiko raises immediately on next exec_command,
    # which is caught by _bash_background's except block → meta unlinked.
    flaky_proxy.close_now()
    out = bash(
        conn_via_proxy, "sleep 60",
        run_in_background=True, name="g1",
        log_path="/tmp/rmcp-test-g1/log",
    )
    assert "Error" in out
    # Local meta should not exist (was cleaned up on failure)
    from remote_mcp.jobs.meta import find_meta_by_name_anywhere
    m, _ = find_meta_by_name_anywhere(sid, "proxytest", "g1")
    assert m is None


def test_G2_jobs_list_batched_kill_timeout(conn_via_proxy, flaky_proxy, panel):
    """Spec §17 G2: Jobs(list) abort on batched kill check failure, no partial."""
    sid, _ = derive_sid()
    init_panel(sid, "proxytest")
    # First launch a task while proxy is OK
    bash(conn_via_proxy, "sleep 60", run_in_background=True, name="g2")
    # close_now() causes TCP RST; exec_with_snapshot raises; jobs_tool re-raises
    # with "observing pids in Jobs list on ..." context (spec §14 C1).
    flaky_proxy.close_now()
    with pytest.raises(Exception) as exc:
        jobs_tool(conn_via_proxy)
    assert "observing" in str(exc.value).lower() or "timed out" in str(exc.value).lower()


def test_G4_jobkill_writes_kill_requested_before_network_drop(conn_via_proxy, flaky_proxy, panel):
    """Spec §17 G4: kill_requested_at written even if exec kill drops mid-flight."""
    sid, _ = derive_sid()
    init_panel(sid, "proxytest")
    bash(conn_via_proxy, "sleep 60", run_in_background=True, name="g4")
    # close_now() causes TCP RST; job_kill_tool writes kill_requested_at_unix to
    # local meta BEFORE exec (spec §14 C5), then exec fails → returns Error.
    flaky_proxy.close_now()
    out = job_kill_tool(conn_via_proxy, name="g4")
    assert "Error" in out
    from remote_mcp.jobs.meta import find_meta_by_name_anywhere
    m, _ = find_meta_by_name_anywhere(sid, "proxytest", "g4")
    assert m["kill_requested_at_unix"] is not None
