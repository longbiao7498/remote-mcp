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


def test_list_tools_returns_thirteen(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        tools = asyncio.run(srv.list_tools())
        names = [t.name for t in tools]
        assert set(names) == {
            "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
            "Bash", "Glob", "Grep", "Feedback",
            "Upload", "Download", "RemoteInfo",
        }
    finally:
        srv._teardown_for_test()


def test_call_tool_dispatches_remote_info(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        result = asyncio.run(srv.call_tool("RemoteInfo", {}))
        text = result[0].text
        assert "host=test" in text
        assert "user=" in text
        assert "hostname=" in text
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


def test_call_tool_appends_unified_suffix_to_bash(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        result = asyncio.run(srv.call_tool("Bash", {"command": "echo hi"}))
        text = result[0].text
        assert text.endswith("[host=test cwd=" + srv._conn.config.cwd + "]")
        assert "hi" in text
    finally:
        srv._teardown_for_test()


def test_call_tool_appends_unified_suffix_to_read(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        asyncio.run(srv.call_tool("Write", {
            "file_path": "/tmp/rmcp-suffix-test.txt",
            "content": "ok\n",
        }))
        result = asyncio.run(srv.call_tool("Read", {
            "file_path": "/tmp/rmcp-suffix-test.txt",
        }))
        text = result[0].text
        assert text.endswith("[host=test cwd=" + srv._conn.config.cwd + "]")
    finally:
        srv._teardown_for_test()


def test_call_tool_appends_unified_suffix_to_error(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        result = asyncio.run(srv.call_tool("Read", {
            "file_path": "/tmp/this-does-not-exist-rmcp-12345",
        }))
        text = result[0].text
        assert "Error: File not found" in text
        assert text.endswith("[host=test cwd=" + srv._conn.config.cwd + "]")
    finally:
        srv._teardown_for_test()


def test_call_tool_appends_unified_suffix_to_feedback(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        result = asyncio.run(srv.call_tool("Feedback", {
            "category": "enhancement",
            "summary": "x",
            "details": "y",
        }))
        text = result[0].text
        assert text.endswith("[host=test cwd=" + srv._conn.config.cwd + "]")
    finally:
        srv._teardown_for_test()


def test_call_tool_reconnect_warning_simplified(runtime_config, sshd_kill_and_restart):
    srv._init_for_test(runtime_config, "test")
    try:
        asyncio.run(srv.call_tool("Bash", {"command": "echo a"}))
        sshd_kill_and_restart(srv._conn)
        result = asyncio.run(srv.call_tool("Glob", {
            "pattern": "*", "path": "/tmp",
        }))
        text = result[0].text
        assert "[WARNING] SSH connection to test was lost and has been re-established" in text
        assert "Snapshot was rebuilt" in text
        # New simplified text — NOT containing the old "shell state was reset" phrase
        assert "shell state was reset" not in text
        assert "working directory is now $HOME" not in text
    finally:
        srv._teardown_for_test()
