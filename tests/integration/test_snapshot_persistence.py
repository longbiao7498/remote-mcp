"""bug #4 — snapshot lives in ~/.cache and is cached locally. v0.2.2."""
import os

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="snaptest",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    yield c
    c.close()


def test_snapshot_path_under_home_cache(conn):
    """Snapshot file lives at ~/.cache/remote-mcp/snapshot-<pid>.sh."""
    assert conn._snapshot_path is not None
    pid = os.getpid()
    expected_suffix = f"/.cache/remote-mcp/snapshot-{pid}.sh"
    assert conn._snapshot_path.endswith(expected_suffix), (
        f"snapshot path {conn._snapshot_path!r} does not end with "
        f"{expected_suffix!r}"
    )


def test_snapshot_content_cached_locally(conn):
    """Content captured at connect is held in self._snapshot_content."""
    assert conn._snapshot_content is not None
    assert isinstance(conn._snapshot_content, bytes)
    assert b"declare" in conn._snapshot_content  # has env data


def test_snapshot_remote_home_resolved_and_cached(conn):
    """_remote_home is populated after connect and starts with /."""
    assert conn._remote_home is not None
    assert conn._remote_home.startswith("/")


def test_snapshot_file_exists_on_remote(conn):
    """The uploaded file is actually on the remote."""
    r = conn.exec(f"test -f {conn._snapshot_path} && echo OK")
    assert r.stdout.strip() == "OK"


def test_connect_alone_does_not_capture_snapshot(sshd_container, ssh_key):
    """After connect(), snapshot must not be captured. Caller is responsible."""
    cfg = HostConfig(
        name="nostartup",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()  # alone — no _capture_snapshot call
    try:
        assert c._snapshot_content is None
        assert c._snapshot_path is None
    finally:
        c.close()


def test_close_does_not_delete_snapshot_file(sshd_container, ssh_key):
    """close() must leave the remote snapshot file in place (persists in ~/.cache/)."""
    import paramiko
    cfg = HostConfig(
        name="persistent",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    c._capture_snapshot()
    snap_path = c._snapshot_path
    c.close()
    # Verify file still exists via raw paramiko (do NOT use SSHConnection — it
    # would write a fresh snapshot at the same path if connected with same PID)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        sshd_container["host"],
        port=sshd_container["port"],
        username=sshd_container["user"],
        key_filename=ssh_key["private_path"],
        timeout=5,
    )
    try:
        stdin, stdout, _ = client.exec_command(
            f"test -f {snap_path} && echo PRESENT || echo GONE"
        )
        out = stdout.read().decode().strip()
        assert out == "PRESENT", f"snapshot file at {snap_path} was deleted by close()"
    finally:
        client.close()


def test_reconnect_when_file_present_does_not_reupload(conn, sshd_kill_and_restart):
    """Most common case: remote file still there → no re-upload, no flag set."""
    sshd_kill_and_restart(conn)
    conn._do_reconnect()
    assert conn._snapshot_reuploaded is False
    assert conn._snapshot_error is None


def test_reconnect_when_file_missing_reuploads(conn, sshd_kill_and_restart):
    """If remote file is gone, _do_reconnect re-uploads from local cache."""
    # Delete the remote snapshot file out-of-band
    snap_path = conn._snapshot_path
    sftp = conn.get_sftp()
    sftp.remove(snap_path)
    sshd_kill_and_restart(conn)
    conn._do_reconnect()
    # File should be back
    r = conn.exec(f"test -f {snap_path} && echo OK")
    assert r.stdout.strip() == "OK"
    assert conn._snapshot_reuploaded is True
    assert conn._snapshot_error is None


def test_reconnect_does_not_recapture(conn, sshd_kill_and_restart, monkeypatch):
    """_do_reconnect must NOT call _capture_snapshot (bashrc must not be re-run)."""
    capture_calls = {"count": 0}
    orig = conn._capture_snapshot

    def spy():
        capture_calls["count"] += 1
        orig()

    monkeypatch.setattr(conn, "_capture_snapshot", spy)
    sshd_kill_and_restart(conn)
    conn._do_reconnect()
    assert capture_calls["count"] == 0
