"""F-group acceptance: sid derivation + cross-session isolation (spec §17 F)."""
import re
import subprocess

import pytest

from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
from remote_mcp.tools.remote_info import remote_info


@pytest.fixture(autouse=True)
def _reset():
    reset_cache_for_test()


def test_F1_remote_info_includes_sid():
    from remote_mcp.config import HostConfig

    class _StubConn:
        config = HostConfig(name="X", hostname="h", port=22, user="u", cwd="/")
    out = remote_info(_StubConn())
    assert re.search(r"sid: [0-9a-f]{12} \(source=", out)


def test_F2_sid_stable_across_reset(tmp_path, monkeypatch):
    """Re-derive after cache clear yields same sid (PPID + ptime unchanged)."""
    s1, _ = derive_sid()
    reset_cache_for_test()
    s2, _ = derive_sid()
    assert s1 == s2


def test_F3_different_processes_get_different_sids():
    """Two independent MCP-server-like processes get different sids (spec §17 F3).

    Simulates two separate Claude Code sessions each spawning their own MCP server
    process: the MCP server's PPID is the Claude Code PID, which differs per session.

    We use two-level subprocess nesting so the sid-deriving process has a unique
    PPID (the intermediate python process, which differs between the two chains):
        pytest → python_A → python_A_child (derives sid using PPID=python_A.pid)
        pytest → python_B → python_B_child (derives sid using PPID=python_B.pid)

    Since python_A.pid ≠ python_B.pid, the two children derive different sids.
    """
    # Each outer script spawns an inner subprocess that derives the sid.
    # The inner subprocess's PPID = outer process's PID (unique per chain).
    outer_code = (
        "import subprocess, sys; "
        "inner = ( "
        "  'import sys; sys.path.insert(0, \\'.\\'); ' "
        "  'from remote_mcp.jobs.sid import derive_sid; ' "
        "  'print(derive_sid()[0])' "
        "); "
        "r = subprocess.run([sys.executable, '-c', inner], capture_output=True, text=True); "
        "print(r.stdout.strip())"
    )
    r1 = subprocess.run(["python", "-c", outer_code], capture_output=True, text=True)
    r2 = subprocess.run(["python", "-c", outer_code], capture_output=True, text=True)
    s1, s2 = r1.stdout.strip(), r2.stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{12}", s1), f"r1 stdout not a valid sid: {r1.stdout!r} stderr={r1.stderr!r}"
    assert re.fullmatch(r"[0-9a-f]{12}", s2), f"r2 stdout not a valid sid: {r2.stdout!r} stderr={r2.stderr!r}"
    assert s1 != s2, f"Expected different sids for different parent processes, got {s1!r} twice"
