"""Unit tests for state derivation + observation parsing (spec §7 + §8.5)."""
from remote_mcp.jobs.state import (
    derive_state, build_batched_kill_check, parse_batched_kill_output,
)


def test_derive_state_running():
    assert derive_state(alive=True, kill_requested=False) == "running"


def test_derive_state_stopped():
    assert derive_state(alive=False, kill_requested=False) == "stopped"


def test_derive_state_killed():
    assert derive_state(alive=False, kill_requested=True) == "killed"


def test_derive_state_kill_failed():
    assert derive_state(alive=True, kill_requested=True) == "kill_failed"


def test_build_batched_empty_pids():
    cmd = build_batched_kill_check([])
    # Only date echo, no for loop body
    assert "date +%s" in cmd


def test_build_batched_with_pids():
    cmd = build_batched_kill_check([100, 200, 300])
    assert "100" in cmd and "200" in cmd and "300" in cmd
    assert "kill -0" in cmd


def test_parse_batched_output():
    out = """now=1748685700
100=A
200=D
300=A
"""
    now, alive_map = parse_batched_kill_output(out)
    assert now == 1748685700
    assert alive_map == {100: True, 200: False, 300: True}
