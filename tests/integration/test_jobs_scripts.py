"""Integration tests for status.sh local + remote handling (spec §9 + §C6)."""
import pytest
import paramiko

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.jobs.init import init_panel
from remote_mcp.jobs.scripts import (
    set_status_script, clear_status_script, run_status_script,
)
from remote_mcp.jobs.paths import remote_status_path, local_status_path


SID = "test000000sc"


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    init_panel(SID, "scripthost")


@pytest.fixture
def conn(sshd_container, ssh_key, panel):
    cfg = HostConfig(
        name="scripthost",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    yield c
    # Cleanup remote status files for this test
    try:
        sftp = c.get_sftp()
        sftp.remove(f".cache/remote-mcp-{SID}-1-status.sh")
    except Exception:
        pass
    c.close()


def test_set_status_writes_local_and_uploads_remote(conn):
    set_status_script(conn, SID, "scripthost", 1, "echo hello", timeout=5)
    assert local_status_path(SID, "scripthost", 1).read_text() == "echo hello"
    sftp = conn.get_sftp()
    remote = sftp.open(f".cache/remote-mcp-{SID}-1-status.sh", "r").read().decode()
    assert remote == "echo hello"


def test_run_status_returns_exec_result(conn):
    set_status_script(conn, SID, "scripthost", 1, "echo hi", timeout=5)
    result = run_status_script(conn, SID, "scripthost", 1, timeout=5)
    assert result.exit_code == 0
    assert result.stdout.strip() == "hi"


def test_run_status_reuploads_if_cache_missing(conn):
    set_status_script(conn, SID, "scripthost", 1, "echo persisted", timeout=5)
    sftp = conn.get_sftp()
    sftp.remove(f".cache/remote-mcp-{SID}-1-status.sh")
    # Should re-upload from local + run
    result = run_status_script(conn, SID, "scripthost", 1, timeout=5)
    assert result.exit_code == 0
    assert result.stdout.strip() == "persisted"


def test_clear_status_removes_local_only(conn):
    set_status_script(conn, SID, "scripthost", 1, "echo gone", timeout=5)
    clear_status_script(conn, SID, "scripthost", 1)
    assert not local_status_path(SID, "scripthost", 1).exists()
    sftp = conn.get_sftp()
    # Remote cache should still be there (per spec §9.2.2)
    assert sftp.stat(f".cache/remote-mcp-{SID}-1-status.sh") is not None
