"""Unit tests for meta.json read/write + atomic id alloc (spec §6 + §5.3.2 step 1)."""
import json
import threading
import time
from pathlib import Path

import pytest

from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.meta import (
    read_meta, write_meta, allocate_id, write_state,
    list_active_metas, list_archive_metas, list_zombie_metas,
    find_meta_by_id_anywhere, find_meta_by_name_anywhere,
    move_to_archive, move_to_zombie,
)
from remote_mcp.jobs.paths import (
    local_meta_path, local_archive_dir, local_zombie_dir,
)


SID = "testsid000000"
HOST = "testhost"


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    init_panel(SID, HOST)
    yield


def _sample_meta(id_=1, name="t1", state="running"):
    return {
        "id": id_,
        "name": name,
        "description": "",
        "command": "sleep 100",
        "log_path": "/tmp/foo.log",
        "host": HOST,
        "pid": 12345,
        "started_at": "2026-05-31T00:00:00Z",
        "started_at_unix": 1748649600,
        "state": state,
        "state_at_unix": 1748649600,
        "kill_requested_at": None,
        "kill_requested_at_unix": None,
        "kill_attempts": [],
        "script_timeout": None,
        "archived_at": None,
        "archived_at_unix": None,
        "zombie": False,
    }


def test_write_then_read_meta_roundtrip(panel):
    m = _sample_meta(id_=1, name="r1")
    write_meta(SID, HOST, m)
    m2 = read_meta(local_meta_path(SID, HOST, 1))
    assert m2["name"] == "r1"
    assert m2["pid"] == 12345


def test_allocate_id_monotonic(panel):
    a = allocate_id(SID, HOST)
    b = allocate_id(SID, HOST)
    c = allocate_id(SID, HOST)
    assert (a, b, c) == (1, 2, 3)


def test_allocate_id_thread_safe(panel):
    """fcntl flock keeps concurrent allocations from colliding."""
    results = []
    barrier = threading.Barrier(10)
    def _alloc():
        barrier.wait()
        results.append(allocate_id(SID, HOST))
    threads = [threading.Thread(target=_alloc) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(results) == list(range(1, 11))


def test_write_state_updates_meta(panel):
    m = _sample_meta(id_=1, name="s1", state="running")
    write_meta(SID, HOST, m)
    write_state(SID, HOST, 1, "stopped", 1748649700, in_dir="active")
    m2 = read_meta(local_meta_path(SID, HOST, 1))
    assert m2["state"] == "stopped"
    assert m2["state_at_unix"] == 1748649700


def test_list_active_metas(panel):
    write_meta(SID, HOST, _sample_meta(id_=1, name="a"))
    write_meta(SID, HOST, _sample_meta(id_=2, name="b"))
    metas = list_active_metas(SID, HOST)
    assert len(metas) == 2
    assert {m["name"] for m in metas} == {"a", "b"}


def test_find_by_id_searches_active_then_archive_then_zombie(panel):
    write_meta(SID, HOST, _sample_meta(id_=1, name="active"))
    write_meta(SID, HOST, _sample_meta(id_=2, name="archived"))
    move_to_archive(SID, HOST, 2)
    write_meta(SID, HOST, _sample_meta(id_=3, name="zombie"))
    move_to_zombie(SID, HOST, 3)

    assert find_meta_by_id_anywhere(SID, HOST, 1)[0]["name"] == "active"
    assert find_meta_by_id_anywhere(SID, HOST, 2)[0]["name"] == "archived"
    assert find_meta_by_id_anywhere(SID, HOST, 3)[0]["name"] == "zombie"
    assert find_meta_by_id_anywhere(SID, HOST, 99) == (None, None)


def test_find_by_name_searches_active_then_archive_then_zombie(panel):
    write_meta(SID, HOST, _sample_meta(id_=1, name="X"))
    found, location = find_meta_by_name_anywhere(SID, HOST, "X")
    assert found["id"] == 1
    assert location == "active"


def test_move_to_archive_relocates_meta_and_status(panel):
    m = _sample_meta(id_=1, name="mv")
    write_meta(SID, HOST, m)
    # Drop a status.sh next to it
    from remote_mcp.jobs.paths import local_status_path
    local_status_path(SID, HOST, 1).write_text("echo hi")
    move_to_archive(SID, HOST, 1)
    assert not local_meta_path(SID, HOST, 1).exists()
    assert (local_archive_dir(SID, HOST) / "1-meta.json").exists()
    assert (local_archive_dir(SID, HOST) / "1-status.sh").exists()


def test_move_to_zombie_relocates_meta(panel):
    m = _sample_meta(id_=1, name="z")
    write_meta(SID, HOST, m)
    move_to_zombie(SID, HOST, 1)
    assert (local_zombie_dir(SID, HOST) / "1-meta.json").exists()
