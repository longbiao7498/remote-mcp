"""Bash tool. See spec §5 (v0.2.0 non-persistent model)."""
import re
import shlex
import time
import uuid

from ..connection import SSHConnection


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


def _wrap(conn: SSHConnection, command: str) -> str:
    """Wrap user command with snapshot source + /dev/null stdin."""
    if conn._snapshot_path:
        inner = f"source {shlex.quote(conn._snapshot_path)} 2>/dev/null || true; {command}"
    else:
        inner = command
    quoted = shlex.quote(inner)
    return f"bash --noprofile --norc -c {quoted} </dev/null"


def _bash_foreground(conn: SSHConnection, command: str, timeout: float) -> str:
    """Per-call exec; drain stdout with timeout-aware partial collection."""
    wrapped = _wrap(conn, command)
    client = conn._client
    if client is None:
        return f"Error: SSH connection to {conn.config.name} is not open"
    stdin, stdout, stderr = client.exec_command(wrapped, timeout=None)
    channel = stdout.channel

    # Merge stderr → stdout by reading both with a small timeout per recv.
    # Use channel.settimeout to make recv blocking-with-timeout (no busy-poll).
    channel.settimeout(0.2)

    out_chunks: list[bytes] = []
    deadline = time.time() + timeout
    timed_out = False
    while True:
        if channel.exit_status_ready() and not channel.recv_ready() \
                and not channel.recv_stderr_ready():
            break
        if time.time() > deadline:
            timed_out = True
            break
        try:
            data = channel.recv(4096)
            if data:
                out_chunks.append(data)
                continue
        except Exception:
            pass  # timeout on recv — fall through to stderr
        try:
            data = channel.recv_stderr(4096)
            if data:
                out_chunks.append(data)
        except Exception:
            pass  # timeout on recv_stderr — loop continues

    if timed_out:
        # Drain whatever's left, then close
        try:
            while channel.recv_ready():
                out_chunks.append(channel.recv(4096))
            while channel.recv_stderr_ready():
                out_chunks.append(channel.recv_stderr(4096))
        except Exception:
            pass
        try:
            channel.close()
        except Exception:
            pass
        partial = b"".join(out_chunks).decode("utf-8", errors="replace")
        partial = partial.replace("\r\n", "\n").replace("\r", "")
        cap = conn.config.bash_output_cap
        if len(partial) > cap:
            partial = partial[:cap] + f"\n... [truncated to {cap} bytes]"
        if partial:
            return f"{partial}\n\nError: Command timed out after {timeout}s on {conn.config.name}"
        return f"Error: Command timed out after {timeout}s on {conn.config.name}"

    # Normal exit: ensure full drain
    try:
        while channel.recv_ready():
            out_chunks.append(channel.recv(4096))
        while channel.recv_stderr_ready():
            out_chunks.append(channel.recv_stderr(4096))
    except Exception:
        pass
    exit_code = channel.recv_exit_status()
    output = b"".join(out_chunks).decode("utf-8", errors="replace")
    output = output.replace("\r\n", "\n").replace("\r", "")
    try:
        channel.close()
    except Exception:
        pass

    if exit_code != 0:
        output = output + f"\n[Exit code: {exit_code}]" if output \
            else f"[Exit code: {exit_code}]"

    cap = conn.config.bash_output_cap
    if len(output) > cap:
        output = output[:cap] + f"\n... [truncated to {cap} bytes]"
    return output


def _bash_background(conn: SSHConnection, command: str) -> str:
    """Per-call exec; launches setsid+nohup so it survives channel close.

    Sources the snapshot inside the background bash so the configured cwd
    (cd <cwd> at the end of the snapshot) and user PATH/aliases are in
    effect for the background command. Matches foreground behavior.
    """
    bg_uuid = uuid.uuid4().hex[:12]
    log_path = f"/tmp/rmcp-bg-{bg_uuid}.log"

    # Build the inner bash command: source snapshot (if available) then run user command
    if conn._snapshot_path:
        inner = (
            f"source {shlex.quote(conn._snapshot_path)} 2>/dev/null || true; "
            f"{command}"
        )
    else:
        inner = command
    quoted_inner = shlex.quote(inner)
    quoted_log = shlex.quote(log_path)

    # setsid: session leader so `kill -- -<pid>` kills the whole group
    # nohup: belt-and-suspenders for SIGHUP
    # </dev/null on outer bash: detach background from our session's stdin
    # subshell-with-echo captures $! reliably
    wrap = (
        f"( setsid nohup bash --noprofile --norc -c {quoted_inner} "
        f"> {quoted_log} 2>&1 </dev/null & echo \"BG_PID=$!\" )"
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
            f"Error: failed to launch background task on {conn.config.name}. "
            f"Output: {output[:500]}"
        )
    m = re.search(r"BG_PID=(\d+)", output)
    if not m:
        return (
            f"Error: failed to start background task on {conn.config.name}. "
            f"Output: {output[:500]}"
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
