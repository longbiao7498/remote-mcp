"""Hardcoded thresholds for job panel (spec §14 C9).

NOT configurable via config.yaml — kept as code-level constants for
simplicity and to avoid users tuning them into broken territory.
"""

KILL_FAIL_PER_TASK_THRESHOLD = 3
"""Per-task kill_attempts count at which Jobs/JobKill triggers L1 NOTE."""

STUCK_KILL_WARN_THRESHOLD = 5
"""Per-host count of stuck_kill tasks at which JobKill triggers L2 WARNING."""

ZOMBIE_WARN_THRESHOLD = 5
"""Per-host count of zombie tasks at which JobArchive(as_zombie=True)
triggers escalation warning."""
