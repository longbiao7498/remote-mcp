"""Bash tool. See spec §5 (v0.2.0 non-persistent model)."""
import re
import shlex
import uuid

from ..connection import SSHConnection, exec_with_snapshot


def bash(conn: SSHConnection, command: str,
         run_in_background: bool = False,
         timeout: float = None,
         description: str = "") -> str:
    """
    Execute a shell command on the remote host (non-persistent per spec §5).

    Foreground (default): per-call exec_command, wraps the command as
    `bash --noprofile --norc -c "source <snapshot>; <cmd>" </dev/null`.
    Each call is a fresh shell — cwd, env, source'd venvs do NOT persist
    across calls (use `cd dir && cmd` or `VAR=v cmd` inline).

    Background (`run_in_background=True`): launches with `setsid nohup`.
    Returns immediately with PID + log path + manipulation templates.

    Args:
        conn: established SSHConnection.
        command: user's shell command (verbatim).
        run_in_background: if True, fire-and-forget process group.
        timeout: foreground timeout (s); None → conn.config.bash_timeout_default.
        description: schema-compat placeholder (unused).

    Returns:
        Output string. Errors return `Error: ...` (never raises).
        Capped at `conn.config.bash_output_cap` bytes (default 100 KB).
    """
    if timeout is None:
        timeout = float(conn.config.bash_timeout_default)
    if run_in_background:
        return _bash_background(conn, command)
    return _bash_foreground(conn, command, timeout)


def _bash_foreground(conn: SSHConnection, command: str, timeout: float) -> str:
    """Per-call exec via exec_with_snapshot helper (§19)."""
    # SSH-layer exceptions bubble up for server.py's _with_reconnect_only.
    result = exec_with_snapshot(conn, command, timeout)

    # v0.3.0 behavior change from v0.2.x: stdout is placed first, then stderr
    # (concatenated, not interleaved). v0.2.x merged them in receive order.
    # Separate buffers are required by spec §19.2 for panel/job-status consumers.
    output = result.stdout
    if result.stderr:
        output = output + result.stderr if output else result.stderr

    cap = conn.config.bash_output_cap
    if result.timed_out:
        if len(output) > cap:
            output = output[:cap] + f"\n... [truncated to {cap} bytes]"
        if output:
            return f"{output}\n\nError: Command timed out after {timeout}s on {conn.config.name}"
        return f"Error: Command timed out after {timeout}s on {conn.config.name}"

    exit_code = result.exit_code
    if exit_code == -1 and not output:
        return (
            f"Error: SSH channel to {conn.config.name} closed unexpectedly "
            f"during command (transport likely disconnected; partial output: "
            f"none). The next tool call will trigger reconnect. Re-run this "
            f"command only if it is safe to repeat."
        )

    if exit_code != 0:
        output = output + f"\n[Exit code: {exit_code}]" if output \
            else f"[Exit code: {exit_code}]"

    if len(output) > cap:
        output = output[:cap] + f"\n... [truncated to {cap} bytes]"
    return output


def _bash_background(conn: SSHConnection, command: str) -> str:
    """Per-call exec; launches setsid+nohup so it survives channel close.

    bug #3 (v0.2.2): writes PID to /tmp/rmcp-bg-<uuid>.pid before echoing
    BG_PID. If the response to this exec is lost (channel dies mid-call),
    the agent can still recover PIDs via `cat /tmp/rmcp-bg-*.pid` because
    the remote pidfile was written before the echo that would have been lost.

    Sources the snapshot inside the background bash so the configured cwd
    (cd <cwd> at the end of the snapshot) and user PATH/aliases are in
    effect for the background command. Matches foreground behavior.
    """
    bg_uuid = uuid.uuid4().hex[:12]
    log_path = f"/tmp/rmcp-bg-{bg_uuid}.log"
    pidfile_path = f"/tmp/rmcp-bg-{bg_uuid}.pid"

    if conn._snapshot_path:
        inner = (
            f"source {shlex.quote(conn._snapshot_path)} 2>/dev/null || true; "
            f"{command}"
        )
    else:
        inner = command
    quoted_inner = shlex.quote(inner)
    quoted_log = shlex.quote(log_path)
    quoted_pidfile = shlex.quote(pidfile_path)

    # bug #3: write PID to pidfile BEFORE echoing BG_PID — if echo response
    # is lost, agent can find the PID via `cat /tmp/rmcp-bg-*.pid`.
    wrap = (
        f"( setsid nohup bash --noprofile --norc -c {quoted_inner} "
        f"> {quoted_log} 2>&1 </dev/null & "
        f"PID=$!; "
        f"echo $PID > {quoted_pidfile}; "
        f"echo \"BG_PID=$PID\" )"
    )
    client = conn._client
    if client is None:
        return f"Error: SSH connection to {conn.config.name} is not open"
    stdin, stdout, stderr = client.exec_command(wrap, timeout=10.0)
    output = stdout.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    try:
        stdout.channel.close()
    except Exception:
        pass
    if exit_code != 0:
        return (
            f"Error: background launch on {conn.config.name} may have started "
            f"but the response was lost. Inspect /tmp/rmcp-bg-*.pid on remote "
            f"to recover PIDs of any orphan processes "
            f"(use `cat /tmp/rmcp-bg-*.pid` then `kill -0 <pid>` to filter "
            f"live ones). Launch output: {output[:500]}"
        )
    m = re.search(r"BG_PID=(\d+)", output)
    if not m:
        return (
            f"Error: background launch on {conn.config.name} may have started "
            f"but the response was lost. Inspect /tmp/rmcp-bg-*.pid on remote "
            f"to recover PIDs of any orphan processes "
            f"(use `cat /tmp/rmcp-bg-*.pid` then `kill -0 <pid>` to filter "
            f"live ones). Launch output: {output[:500]}"
        )
    pid = m.group(1)
    return (
        f"Started background task.\n"
        f"  PID: {pid}\n"
        f"  Log: {log_path}\n\n"
        f"To check status:    Bash(\"kill -0 {pid} && echo running || echo done\")\n"
        f"To read new output: Read(\"{log_path}\", offset=<last_line+1>)\n"
        f"To stop gracefully: Bash(\"kill -TERM -- -{pid}\")\n"
        f"To force stop:      Bash(\"kill -KILL -- -{pid}\")\n"
    )
