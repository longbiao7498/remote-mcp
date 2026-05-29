"""bug #1 — Edit must not be auto-retried when SSH fails. v0.2.2."""
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


def test_edit_does_not_auto_retry_on_ssh_failure(runtime_config, sshd_kill_and_restart):
    """When SSH dies mid-Edit, agent gets one Error: response — no transparent
    success from a second attempt that would see old_string already replaced."""
    srv._init_for_test(runtime_config, "test")
    try:
        # Pre-populate a file
        asyncio.run(srv.call_tool("Write", {
            "file_path": "/tmp/rmcp-edit-retry-test.txt",
            "content": "before\n",
        }))
        # Kill the transport so Edit hits SSH errors immediately
        sshd_kill_and_restart(srv._conn)
        # Call Edit — should return Error string without retrying
        result = asyncio.run(srv.call_tool("Edit", {
            "file_path": "/tmp/rmcp-edit-retry-test.txt",
            "old_string": "before",
            "new_string": "after",
        }))
        text = result[0].text
        assert "Error:" in text, f"expected Error: ..., got: {text!r}"
    finally:
        srv._teardown_for_test()
