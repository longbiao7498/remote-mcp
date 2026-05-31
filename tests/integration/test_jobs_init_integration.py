"""H-group acceptance tests for startup init (spec §17 H)."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from remote_mcp.jobs.paths import (
    local_sid_host_dir, local_archive_dir, local_zombie_dir, local_next_id_path,
)
from remote_mcp.jobs.sid import reset_cache_for_test


@pytest.fixture
def isolated_panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_cache_for_test()
    yield tmp_path


def test_H1_first_startup_creates_full_tree(isolated_panel):
    """Spec §17 H1: directories + archive/zombie subdirs + next_id=0."""
    from remote_mcp.jobs.init import init_panel
    from remote_mcp.jobs.sid import derive_sid
    sid, _ = derive_sid()
    init_panel(sid, "h1host")
    assert local_sid_host_dir(sid, "h1host").is_dir()
    assert local_archive_dir(sid, "h1host").is_dir()
    assert local_zombie_dir(sid, "h1host").is_dir()
    assert local_next_id_path(sid, "h1host").read_text().strip() == "0"


def test_H2_idempotent(isolated_panel):
    """Existing next_id is preserved across reinit."""
    from remote_mcp.jobs.init import init_panel
    from remote_mcp.jobs.sid import derive_sid
    sid, _ = derive_sid()
    init_panel(sid, "h2host")
    local_next_id_path(sid, "h2host").write_text("7")
    init_panel(sid, "h2host")
    assert local_next_id_path(sid, "h2host").read_text().strip() == "7"


def test_H3_unwritable_path_raises(isolated_panel, monkeypatch):
    # /proc/no-write-here does not exist and /proc itself is not writable by
    # normal users, so mkdir will raise OSError (FileNotFoundError / EACCES).
    # Use /proc/no-write-here as the XDG root — it is a reliable unwritable
    # target on Linux without needing root.
    monkeypatch.setenv("XDG_DATA_HOME", "/proc/no-write-here")
    reset_cache_for_test()
    from remote_mcp.jobs.init import init_panel
    from remote_mcp.jobs.sid import derive_sid
    sid, _ = derive_sid()
    with pytest.raises(OSError):
        init_panel(sid, "h3host")
