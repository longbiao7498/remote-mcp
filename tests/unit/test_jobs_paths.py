"""Unit tests for jobs path computation (spec §4)."""
from pathlib import Path

from remote_mcp.jobs.paths import (
    local_jobpane_root, local_sid_host_dir, local_archive_dir,
    local_zombie_dir, local_meta_path, local_status_path,
    local_next_id_path, local_id_lock_path,
    remote_pid_path, remote_status_path, remote_default_log_path,
)


SID = "a1b2c3d4e5f6"
HOST = "prod"
ID = 17


def test_local_jobpane_root_is_under_xdg_data_home():
    p = local_jobpane_root()
    # Expect ~/.local/share/remote-mcp/jobpane/ or $XDG_DATA_HOME/remote-mcp/jobpane/
    assert "remote-mcp" in str(p)
    assert "jobpane" in str(p)


def test_local_sid_host_dir():
    p = local_sid_host_dir(SID, HOST)
    assert str(p).endswith(f"/jobpane/{SID}/{HOST}")


def test_local_archive_and_zombie_dirs():
    archive = local_archive_dir(SID, HOST)
    zombie = local_zombie_dir(SID, HOST)
    assert str(archive).endswith(f"/{SID}/{HOST}/archive")
    assert str(zombie).endswith(f"/{SID}/{HOST}/zombie")


def test_local_meta_and_status_paths():
    meta = local_meta_path(SID, HOST, ID)
    status = local_status_path(SID, HOST, ID)
    assert str(meta).endswith(f"/{SID}/{HOST}/{ID}-meta.json")
    assert str(status).endswith(f"/{SID}/{HOST}/{ID}-status.sh")


def test_local_next_id_and_lock_paths():
    n = local_next_id_path(SID, HOST)
    lock = local_id_lock_path(SID, HOST)
    assert str(n).endswith(f"/{SID}/{HOST}/next_id")
    assert str(lock).endswith(f"/{SID}/{HOST}/.id_lock")


def test_remote_pid_path_flat_naming():
    p = remote_pid_path(SID, ID)
    # Flat name in ~/.cache/, with literal ~ for remote-side expansion
    assert p == f"~/.cache/remote-mcp-{SID}-{ID}-pid"


def test_remote_status_path_flat_naming():
    assert remote_status_path(SID, ID) == f"~/.cache/remote-mcp-{SID}-{ID}-status.sh"


def test_remote_default_log_path_flat_naming():
    assert remote_default_log_path(SID, ID) == f"~/.cache/remote-mcp-{SID}-{ID}.log"
