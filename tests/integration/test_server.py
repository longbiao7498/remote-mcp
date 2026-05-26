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


def test_list_tools_returns_ten(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        tools = asyncio.run(srv.list_tools())
        names = [t.name for t in tools]
        assert set(names) == {
            "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
            "Bash", "Glob", "Grep", "Feedback",
        }
    finally:
        srv._teardown_for_test()


def test_call_tool_dispatches_read(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        # Write a file first
        result = asyncio.run(srv.call_tool("Write", {
            "file_path": "/tmp/rmcp-srv-test.txt",
            "content": "hi\n",
        }))
        assert "Successfully wrote" in result[0].text

        result = asyncio.run(srv.call_tool("Read", {
            "file_path": "/tmp/rmcp-srv-test.txt",
        }))
        assert "     1\thi" in result[0].text
    finally:
        srv._teardown_for_test()


def test_call_tool_reconnect_warning(runtime_config, sshd_kill_and_restart):
    srv._init_for_test(runtime_config, "test")
    try:
        # First call succeeds
        asyncio.run(srv.call_tool("Bash", {"command": "echo a"}))
        # Force-close the socket; next call triggers reconnect → WARNING
        sshd_kill_and_restart(srv._conn)
        # Call Glob (uses exec_with_retry via _with_retry wrapper)
        result = asyncio.run(srv.call_tool("Glob", {
            "pattern": "*", "path": "/tmp",
        }))
        text = result[0].text
        assert "[WARNING] SSH connection to test was lost" in text
    finally:
        srv._teardown_for_test()
