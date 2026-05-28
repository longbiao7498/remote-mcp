"""MCP server: list_tools, call_tool, dispatch, reconnect WARNING. See spec §5.4."""
import asyncio
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import RootConfig, load_config
from .connection import SSHConnection
from .schemas import ALL_TOOL_SCHEMAS, ALL_TOOL_DESCRIPTIONS

from .tools import bash as bash_tool
from .tools import edit as edit_tool
from .tools import feedback as feedback_tool
from .tools import file_stat as file_stat_tool
from .tools import glob as glob_tool
from .tools import grep as grep_tool
from .tools import multi_edit as multi_edit_tool
from .tools import multi_read as multi_read_tool
from .tools import read as read_tool
from .tools import upload as upload_tool
from .tools import download as download_tool
from .tools import remote_info as remote_info_tool
from .tools import write as write_tool


app = Server("remote-mcp")

_conn: Optional[SSHConnection] = None
_root_config: Optional[RootConfig] = None


@app.list_tools()
async def list_tools():
    return [
        Tool(name=name,
             description=ALL_TOOL_DESCRIPTIONS[name],
             inputSchema=ALL_TOOL_SCHEMAS[name])
        for name in ALL_TOOL_SCHEMAS
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    global _conn, _root_config

    # ALL tools dispatch through _with_retry per spec §9.
    result = _with_retry(lambda: _raw_dispatch(name, arguments))

    # Reconnect WARNING prefix (only on successful reconnect, spec §5.6)
    prefix = ""
    if _conn is not None and _conn.check_and_clear_reconnect_flag():
        prefix = (
            f"[WARNING] SSH connection to {_conn.config.name} was lost "
            f"and has been re-established. Snapshot was rebuilt; if your "
            f"bashrc has changed since the connection started, the new "
            f"state takes effect from this point.\n\n"
        )

    # Unified suffix — append to every tool output (success + error)
    suffix = ""
    if _conn is not None:
        suffix = f"\n\n[host={_conn.config.name} cwd={_conn.config.cwd}]"

    return [TextContent(type="text", text=prefix + result + suffix)]


def _raw_dispatch(name: str, args: dict) -> str:
    if name == "Read":
        return read_tool.read(_conn, **args)
    if name == "Write":
        return write_tool.write(_conn, **args)
    if name == "Edit":
        return edit_tool.edit(_conn, **args)
    if name == "MultiEdit":
        return multi_edit_tool.multi_edit(_conn, **args)
    if name == "MultiRead":
        return multi_read_tool.multi_read(_conn, **args)
    if name == "FileStat":
        return file_stat_tool.file_stat(_conn, **args)
    if name == "Bash":
        return bash_tool.bash(_conn, **args)
    if name == "Glob":
        return glob_tool.glob_tool(_conn, **args)
    if name == "Grep":
        return grep_tool.grep_tool(_conn, **args)
    if name == "Feedback":
        return feedback_tool.feedback(
            _conn, _root_config.feedback_path, **args
        )
    if name == "Upload":
        return upload_tool.upload(_conn, **args)
    if name == "Download":
        return download_tool.download(_conn, **args)
    if name == "RemoteInfo":
        return remote_info_tool.remote_info(_conn, **args)
    return f"Error: unknown tool: {name}"


def _with_retry(call):
    """On SSH-level failure, reconnect once then retry. Spec §9."""
    import paramiko
    try:
        return call()
    except (paramiko.SSHException, EOFError, OSError) as e:
        try:
            _conn._do_reconnect()
        except Exception as e2:
            return (
                f"Error: SSH connection to {_conn.config.name} lost and "
                f"reconnect failed: {e2}"
            )
        try:
            return call()
        except Exception as e3:
            return f"Error: {e3}"


async def main(host_name: str, config_path: str, cwd_override: Optional[str] = None) -> None:
    global _conn, _root_config
    _root_config = load_config(config_path)
    host_cfg = _root_config.hosts[host_name]
    if cwd_override is not None:
        host_cfg.cwd = cwd_override
    jump_cfg = None
    if host_cfg.jump_host:
        jump_cfg = _root_config.hosts[host_cfg.jump_host]
    _conn = SSHConnection(host_cfg, jump_config=jump_cfg)
    _conn.connect()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream,
                app.create_initialization_options(),
            )
    finally:
        _conn.close()


# Test helpers
def _init_for_test(root: RootConfig, host_name: str) -> None:
    global _conn, _root_config
    _root_config = root
    host_cfg = root.hosts[host_name]
    jump_cfg = root.hosts.get(host_cfg.jump_host) if host_cfg.jump_host else None
    _conn = SSHConnection(host_cfg, jump_config=jump_cfg)
    _conn.connect()


def _teardown_for_test() -> None:
    global _conn, _root_config
    if _conn is not None:
        _conn.close()
    _conn = None
    _root_config = None
