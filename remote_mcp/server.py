"""MCP server: list_tools, call_tool, dispatch, reconnect WARNING. See spec §5.4."""
import asyncio
import sys
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import RootConfig, load_config
from .connection import SSHConnection
from .schemas import ALL_TOOL_SCHEMAS, ALL_TOOL_DESCRIPTIONS
from .jobs.sid import derive_sid
from .jobs.init import init_panel

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

NO_RETRY_TOOLS: frozenset = frozenset({"Edit", "MultiEdit", "Bash"})


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

    # bug #1 fix: NO_RETRY_TOOLS skip auto-retry to avoid false negatives.
    if name in NO_RETRY_TOOLS:
        result = _with_reconnect_only(lambda: _raw_dispatch(name, arguments))
    else:
        result = _with_retry(lambda: _raw_dispatch(name, arguments))

    prefix = ""

    # bug #4 fix: startup snapshot failure (independent of reconnect).
    # Shown once on the first call after startup failure.
    if _conn is not None and _conn._startup_warning_pending:
        prefix += (
            f"[WARNING] Session-start snapshot capture failed "
            f"({_conn._snapshot_error}). Bash calls will run without the "
            f"user's PATH/aliases, and will start in $HOME instead of the "
            f"configured cwd ({_conn.config.cwd}).\n\n"
        )
        _conn._startup_warning_pending = False

    # Reconnect WARNING — three variants depending on snapshot state.
    if _conn is not None and _conn.check_and_clear_reconnect_flag():
        if not _conn._snapshot_reuploaded:
            # Case A: file still present, nothing changed
            prefix += (
                f"[WARNING] SSH connection to {_conn.config.name} was lost "
                f"and has been re-established.\n\n"
            )
        elif _conn._snapshot_error is None:
            # Case B: re-upload succeeded
            prefix += (
                f"[WARNING] SSH connection to {_conn.config.name} was lost "
                f"and has been re-established. The remote snapshot file was "
                f"missing (likely cleaned externally) and has been re-uploaded "
                f"from the local cache; the environment captured at session "
                f"start has been preserved.\n\n"
            )
        else:
            # Case C: re-upload failed
            prefix += (
                f"[WARNING] SSH connection to {_conn.config.name} was lost "
                f"and has been re-established, but the remote snapshot file "
                f"was missing AND re-upload failed ({_conn._snapshot_error}). "
                f"Subsequent Bash calls will run without the user's "
                f"PATH/aliases, and will start in $HOME instead of the "
                f"configured cwd ({_conn.config.cwd}).\n\n"
            )
        _conn._snapshot_reuploaded = False

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


def _with_reconnect_only(call):
    """For NO_RETRY_TOOLS (spec §5.1): catch SSH-layer exceptions, trigger a
    best-effort reconnect so future calls work, but DO NOT re-execute the
    tool call. Original error is returned as Error: <type>: <message>.

    Rationale: Edit/MultiEdit are read-modify-write and re-executing produces
    bug #1 (false-negative when first write actually succeeded). Bash is
    state-dependent — only the agent knows whether re-running is safe.
    """
    import paramiko
    try:
        return call()
    except (paramiko.SSHException, EOFError, OSError) as e:
        try:
            _conn._do_reconnect()
        except Exception:
            pass  # reconnect failure does not change what we return to agent
        return f"Error: {type(e).__name__}: {e}"


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
    _conn._capture_snapshot()
    if _conn._snapshot_error is not None:
        _conn._startup_warning_pending = True
    sid, sid_source = derive_sid()
    try:
        init_panel(sid, _conn.config.name)
    except OSError as e:
        from pathlib import Path
        print(
            f"Error: cannot init job panel at "
            f"{Path.home()}/.local/share/remote-mcp/jobpane/{sid}/{_conn.config.name}/: "
            f"{e}. Check filesystem permissions / disk space.",
            file=sys.stderr,
        )
        sys.exit(1)
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
    _conn._capture_snapshot()
    if _conn._snapshot_error is not None:
        _conn._startup_warning_pending = True


def _teardown_for_test() -> None:
    global _conn, _root_config
    if _conn is not None:
        _conn.close()
    _conn = None
    _root_config = None
