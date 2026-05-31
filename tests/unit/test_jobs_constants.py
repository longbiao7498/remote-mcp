"""Unit tests for jobs constants (spec §14 C9)."""
from remote_mcp.jobs import constants


def test_thresholds_are_hardcoded():
    assert constants.KILL_FAIL_PER_TASK_THRESHOLD == 3
    assert constants.STUCK_KILL_WARN_THRESHOLD == 5
    assert constants.ZOMBIE_WARN_THRESHOLD == 5
