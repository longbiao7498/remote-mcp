"""bug #4 — three WARNING variants observed end-to-end. v0.2.2."""
import asyncio

import pytest

from remote_mcp.config import HostConfig, RootConfig
from remote_mcp import server as srv


@pytest.fixture
def runtime_config(sshd_container, ssh_key, tmp_path):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    root = RootConfig(
        hosts={"test": cfg},
        default_host="test",
        feedback_path=str(tmp_path / "fb.jsonl"),
    )
    return root


def test_case_a_normal_reconnect_warning(runtime_config, sshd_kill_and_restart):
    """Most common case: reconnect with snapshot file still present."""
    srv._init_for_test(runtime_config, "test")
    try:
        asyncio.run(srv.call_tool("Glob", {"pattern": "*", "path": "/tmp"}))
        sshd_kill_and_restart(srv._conn)
        result = asyncio.run(srv.call_tool("Glob", {"pattern": "*", "path": "/tmp"}))
        text = result[0].text
        assert "was lost and has been re-established." in text
        # Case A does NOT mention re-upload or degraded env
        assert "re-uploaded" not in text
        assert "subsequent bash" not in text.lower()
    finally:
        srv._teardown_for_test()


def test_case_b_remote_file_missing_then_reuploaded(runtime_config, sshd_kill_and_restart):
    """If snapshot file is deleted, reconnect re-uploads and WARNING explains."""
    srv._init_for_test(runtime_config, "test")
    try:
        # Delete the remote snapshot before forcing reconnect
        snap_path = srv._conn._snapshot_path
        sftp = srv._conn.get_sftp()
        sftp.remove(snap_path)
        sshd_kill_and_restart(srv._conn)
        result = asyncio.run(srv.call_tool("Glob", {"pattern": "*", "path": "/tmp"}))
        text = result[0].text
        assert "re-uploaded from the local cache" in text
    finally:
        srv._teardown_for_test()
