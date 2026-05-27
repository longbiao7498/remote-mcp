"""Bash tool. See spec §5.3.7."""
import re
import shlex
import uuid

from ..connection import SSHConnection


def bash(conn: SSHConnection, command: str,
         run_in_background: bool = False,
         timeout: float = None,
         description: str = "") -> str:
    """
    Execute a shell command on the remote host.

    Foreground mode (default): runs in the persistent bash session,
    blocks until done or timeout, returns combined output prefixed with
    `[host=<name> cwd=<pwd>]`. Shell state (cwd, env) persists across
    foreground calls within the same SSH connection.

    Background mode (`run_in_background=True`): wraps the command in
    `setsid nohup ... &`, returns immediately with PID and log path.
    Use the returned `kill -- -<pid>` command to stop (kills the whole
    process group). See `_bash_background` for details.

    Args:
        conn: established SSHConnection.
        command: the user's shell command (verbatim — no extra quoting).
        run_in_background: if True, start as a backgrounded process group.
        timeout: foreground timeout in seconds. None → use
            `conn.config.bash_timeout_default` (default 120).
        description: informational label (not used internally; kept for
            MCP schema compatibility with Claude Code's native Bash).

    Returns:
        Output string. Errors return `"Error: ..."` (never raises).
        Output is capped at `conn.config.bash_output_cap` bytes (default
        100 KB); excess is truncated with a `[truncated to N bytes]` note.
    """
    if timeout is None:
        timeout = float(conn.config.bash_timeout_default)
    if run_in_background:
        return _bash_background(conn, command)
    return _bash_foreground(conn, command, timeout)


def _bash_foreground(conn: SSHConnection, command: str, timeout: float) -> str:
    """Run `command` synchronously in the persistent bash session."""
    session = conn.get_bash_session()
    try:
        result = session.execute(command, timeout=timeout)
    except TimeoutError:
        return f"Error: Command timed out after {timeout}s on {conn.config.name}"

    cwd = session.current_cwd()
    # Strip spurious \r characters introduced by PTY line endings
    output = result.output.replace("\r\n", "\n").replace("\r", "")

    prefix = f"[host={conn.config.name} cwd={cwd}]\n"

    if result.exit_code != 0:
        output += f"\n[Exit code: {result.exit_code}]"

    cap = conn.config.bash_output_cap
    if len(output) > cap:
        output = output[:cap] + f"\n... [truncated to {cap} bytes]"

    return prefix + output


def _bash_background(conn: SSHConnection, command: str) -> str:
    """
    Start command as a background process group leader.
    See spec §5.3.7 — setsid is non-optional.
    """
    session = conn.get_bash_session()
    bg_uuid = uuid.uuid4().hex[:12]
    log_path = f"/tmp/rmcp-bg-{bg_uuid}.log"
    quoted_cmd = shlex.quote(command)
    quoted_log = shlex.quote(log_path)

    # setsid: creates new session, the bash becomes session/group leader (PID = PGID)
    # nohup: belt-and-suspenders against SIGHUP
    # </dev/null: detach stdin
    # ( ... & echo "BG_PID=$!" ): subshell so $! is the bg PID
    wrap = (
        f"( setsid nohup bash -c {quoted_cmd} "
        f"> {quoted_log} 2>&1 </dev/null & echo \"BG_PID=$!\" )"
    )
    try:
        result = session.execute(wrap, timeout=10.0)
    except TimeoutError:
        return f"Error: failed to launch background task on {conn.config.name} (timeout)"

    m = re.search(r"BG_PID=(\d+)", result.output)
    if not m:
        return (
            f"Error: failed to start background task on {conn.config.name}. "
            f"Output: {result.output[:500]}"
        )
    pid = m.group(1)
    cwd = session.current_cwd()

    return (
        f"[host={conn.config.name} cwd={cwd}]\n"
        f"Started background task.\n"
        f"  PID: {pid}\n"
        f"  Log: {log_path}\n\n"
        f"To check status:    Bash(\"kill -0 {pid} && echo running || echo done\")\n"
        f"To read new output: Read(\"{log_path}\", offset=<last_line+1>)\n"
        f"To stop gracefully: Bash(\"kill -TERM -- -{pid}\")\n"
        f"To force stop:      Bash(\"kill -KILL -- -{pid}\")\n"
    )
