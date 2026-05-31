"""Unit tests for panel startup init (spec §4.1)."""
import os
from pathlib import Path

import pytest

from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.paths import (
    local_sid_host_dir, local_archive_dir, local_zombie_dir,
    local_next_id_path,
)


SID = "testsid000000"
HOST = "testhost"


@pytest.fixture
def isolated_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


def test_init_panel_creates_all_dirs_and_next_id(isolated_xdg):
    init_panel(SID, HOST)
    assert local_sid_host_dir(SID, HOST).is_dir()
    assert local_archive_dir(SID, HOST).is_dir()
    assert local_zombie_dir(SID, HOST).is_dir()
    nid = local_next_id_path(SID, HOST)
    assert nid.is_file()
    assert nid.read_text().strip() == "0"


def test_init_panel_is_idempotent(isolated_xdg):
    init_panel(SID, HOST)
    # Write a different value to next_id
    local_next_id_path(SID, HOST).write_text("42")
    # Re-init should NOT clobber
    init_panel(SID, HOST)
    assert local_next_id_path(SID, HOST).read_text().strip() == "42"


def test_init_panel_raises_on_unwritable_parent(isolated_xdg, monkeypatch):
    # Point to a path under /proc which is unwritable
    monkeypatch.setenv("XDG_DATA_HOME", "/proc/no-write")
    with pytest.raises(OSError):
        init_panel(SID, HOST)
