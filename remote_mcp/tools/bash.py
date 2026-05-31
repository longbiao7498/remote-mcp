"""Bash tool. See spec §5 (v0.2.0 non-persistent model, extended in v0.3.0)."""
import re as _re
import shlex
import time as _time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from ..connection import SSHConnection, exec_with_snapshot
from ..jobs.sid import derive_sid
from ..jobs.meta import allocate_id, write_meta, find_meta_by_name_anywhere
from ..jobs.paths import (
    local_meta_path,
    remote_pid_path,
    remote_default_log_path,
)


_NAME_RE = _re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_DESCRIPTION_MAX = 500


def _validate_name(name: str) -> Optional[str]:
    """Returns Error string if invalid, None if OK."""
    if not _NAME_RE.fullmatch(name):
        return f"Error: invalid job name '{name}': must match ^[A-Za-z0-9_.-]{{1,64}}$"
    return None


def _generate_name() -> str:
    return f"bg-{_uuid.uuid4().hex[:12]}"


def _truncate_description(desc: str) -> Tuple[str, bool]:
    """Returns (desc, truncated) tuple."""
    if len(desc) <= _DESCRIPTION_MAX:
        return desc, False
    return desc[:_DESCRIPTION_MAX], True


def bash(conn: SSHConnection, command: str, *,
         run_in_background: bool = False,
         timeout: float = None,
         description: str = "",
         log_path: str = None,
         name: str = None) -> str:
    """
    Execute a shell command on the remote host (non-persistent per spec §5).

    Foreground (default): per-call exec_command, wraps the command as
    `bash --noprofile --norc -c "source <snapshot>; <cmd>" </dev/null`.
    Each call is a fresh shell — cwd, env, source'd venvs do NOT persist
    across calls (use `cd dir && cmd` or `VAR=v cmd` inline).

    Background (`run_in_background=True`): launches with `setsid nohup`.
    Returns structured fields: id, name, log_path, pid, started_at.

    Args:
        conn: established SSHConnection.
        command: user's shell command (verbatim).
        run_in_background: if True, fire-and-forget process group.
        timeout: foreground timeout (s); None → conn.config.bash_timeout_default.
        description: task description (stored in panel for background tasks).
        log_path: remote log path (background only; default ~/.cache/...).
        name: job alias (background only; default bg-<uuid12>).

    Returns:
        Output string. Errors return `Error: ...` (never raises).
        Capped at `conn.config.bash_output_cap` bytes (default 100 KB).
    """
    if timeout is None:
        timeout = float(conn.config.bash_timeout_default)
    if run_in_background:
        return _bash_background(conn, command, log_path=log_path,
                                name=name, description=description)
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


def _bash_background(conn: SSHConnection, command: str,
                     log_path: Optional[str],
                     name: Optional[str],
                     description: str) -> str:
    """v0.3.0 background launch (spec §5.3).

    Writes local meta, decides log_path, does remote mkdir, runs new wrap with
    started_at echoes + pid write, parses 3-line response, falls back to SFTP
    read on response loss, deletes local meta if unable to confirm pid.
    """
    host = conn.config.name
    sid, _ = derive_sid()

    # 1. Validate name (or generate)
    if name is None:
        name = _generate_name()
    else:
        err = _validate_name(name)
        if err:
            return err

    # 2. Truncate description
    desc, desc_truncated = _truncate_description(description)

    # 3. Name uniqueness in active dir
    found, location = find_meta_by_name_anywhere(sid, host, name)
    if found is not None and location == "active":
        return (
            f"Error: job name '{name}' already in active panel; archive the "
            f"old one with JobArchive(name='{name}') or pick a different name"
        )

    # 4. Allocate id
    id_ = allocate_id(sid, host)

    # 5. Decide log_path
    if log_path is None:
        log_path = remote_default_log_path(sid, id_)

    # Expand ~/ to absolute path before writing meta and returning to agent.
    # Spec §5.3.2 step 4: agent-facing tools like Read reject ~-prefixed paths.
    if log_path.startswith("~/"):
        remote_home = getattr(conn, "_remote_home", None)
        if remote_home is not None:
            log_path = remote_home + log_path[1:]  # ~/X → <home>/X

    # 6. Write initial local meta (pid/started_at null; state=running)
    now_unix = int(_time.time())
    meta = {
        "id": id_, "name": name, "description": desc,
        "command": command, "log_path": log_path, "host": host,
        "pid": None, "started_at": None, "started_at_unix": None,
        "state": "running", "state_at_unix": now_unix,
        "kill_requested_at": None, "kill_requested_at_unix": None,
        "kill_attempts": [],
        "script_timeout": None,
        "archived_at": None, "archived_at_unix": None, "zombie": False,
    }
    write_meta(sid, host, meta)

    # 7. Remote mkdir log_path parent
    # Use $(dirname ...) with tilde-safe path: replace ~/ with $HOME/ so bash
    # expands it even inside the subshell (shlex.quote prevents ~ expansion).
    mkdir_log = log_path.replace("~/", "$HOME/", 1) if log_path.startswith("~/") else shlex.quote(log_path)
    mkdir_cmd = f"mkdir -p $(dirname {mkdir_log})"
    try:
        mkr = exec_with_snapshot(conn, mkdir_cmd, timeout=30.0)
    except Exception as e:
        try:
            local_meta_path(sid, host, id_).unlink()
        except Exception:
            pass
        return f"Error: creating log_path parent for '{name}' (id={id_}) on {host}: {e}"

    if mkr.exit_code != 0:
        try:
            local_meta_path(sid, host, id_).unlink()
        except Exception:
            pass
        stderr_lower = mkr.stderr.lower()
        if "not a directory" in stderr_lower or "file exists" in stderr_lower:
            parent = log_path.rsplit("/", 1)[0]
            return (
                f"Error: log_path parent '{parent}' exists but is not a "
                f"directory; cannot mkdir -p"
            )
        return f"Error: cannot create log_path parent: {mkr.stderr.strip()}"

    # 8. Exec wrap
    snap_path = getattr(conn, "_snapshot_path", "") or ""
    snap_clause = (
        f"source {shlex.quote(snap_path)} 2>/dev/null || true\n    "
        if snap_path else ""
    )
    pid_remote = remote_pid_path(sid, id_)
    # For log_path and pid_remote that start with ~/, replace ~/ with $HOME/
    # so bash can expand them (shlex.quote would prevent ~ expansion).
    def _shell_safe_path(p: str) -> str:
        if p.startswith("~/"):
            return "$HOME/" + p[2:]
        return shlex.quote(p)

    log_path_shell = _shell_safe_path(log_path)
    pid_remote_shell = _shell_safe_path(pid_remote)
    wrap = (
        f"( setsid nohup bash --noprofile --norc -c '{snap_clause}{command}' "
        f"> {log_path_shell} 2>&1 </dev/null & "
        f"PID=$!; "
        f"echo $PID > {pid_remote_shell}; "
        f"STARTED_AT_UNIX=$(date +%s); "
        f"STARTED_AT=$(date -u -Iseconds); "
        f"echo \"BG_PID=$PID\"; "
        f"echo \"STARTED_AT_UNIX=$STARTED_AT_UNIX\"; "
        f"echo \"STARTED_AT=$STARTED_AT\" )"
    )
    wresult = None
    wresult_err = ""
    try:
        # Note: spec §19.4 says background wrap "is not in scope" for
        # exec_with_snapshot. We use the helper anyway because (a) the outer
        # shell needs the timeout + ExecResult handling, and (b) the snapshot
        # source in the outer shell is harmless — the actual user command is
        # executed in the detached setsid subshell which sources snapshot
        # explicitly via the inner snap_clause. No double-source effect.
        wresult = exec_with_snapshot(conn, wrap, timeout=10.0)
    except Exception as e:
        wresult_err = str(e)

    # 9. Parse response
    pid, started_at, started_at_unix, fallback_used = None, None, None, False
    if wresult is not None and not wresult.timed_out:
        out = wresult.stdout
        pm = _re.search(r"BG_PID=(\d+)", out)
        sm = _re.search(r"STARTED_AT_UNIX=(\d+)", out)
        sa = _re.search(r"STARTED_AT=(\S+)", out)
        if pm and sm and sa:
            pid = int(pm.group(1))
            started_at_unix = int(sm.group(1))
            started_at = sa.group(1)

    if pid is None:
        # Path B: synchronous SFTP fallback
        pid, started_at, started_at_unix, fallback_used, sftp_detail = _bg_sftp_fallback(
            conn, sid, id_,
        )
        if pid is None:
            # B2: clean up and Error
            try:
                local_meta_path(sid, host, id_).unlink()
            except Exception:
                pass
            if wresult is None:
                exec_detail = f"SSH exception: {wresult_err}"
            elif wresult.timed_out:
                exec_detail = "wrap exec timed out"
            else:
                exec_detail = "missing fields in echo response"
            sftp_msg = sftp_detail if sftp_detail else "unknown SFTP error"
            return (
                f"Error: background launch for '{name}' (id={id_}) on {host} "
                f"could not be confirmed. exec response was lost ({exec_detail}) "
                f"AND SFTP fallback fetch of pid file failed ({sftp_msg}). The task has NOT "
                f"been added to the panel.\n\n"
                f"What this means:\n"
                f"- If SFTP failed because the file is genuinely missing: the "
                f"wrap never ran (or never reached the pid-write step). Nothing "
                f"to clean up.\n"
                f"- If SFTP failed because of network/timeout: the wrap MAY "
                f"have started and a remote process MAY be orphaned. Recover "
                f"with:\n"
                f"    Bash(\"test -f ~/.cache/remote-mcp-{sid}-{id_}-pid && "
                f"cat ~/.cache/remote-mcp-{sid}-{id_}-pid\")\n"
                f"  If that returns a pid, the orphan exists; kill it with\n"
                f"    Bash(\"kill -TERM -- -<pid>\")\n"
                f"  Then optionally Bash(\"rm ~/.cache/remote-mcp-{sid}-{id_}-pid\") "
                f"to clean up the file.\n\n"
                f"You may safely retry Bash(run_in_background=True, ...) with "
                f"the same name (the failed entry has been removed from the panel)."
            )

    # 10. Backfill meta with confirmed pid/started_at
    meta["pid"] = pid
    meta["started_at"] = started_at
    meta["started_at_unix"] = started_at_unix
    write_meta(sid, host, meta)

    # 11. Assemble return
    lines = [
        "Started background task.",
        f"  id: {id_}",
        f"  name: {name}",
        f"  log_path: {log_path}",
        f"  pid: {pid}",
        f"  started_at: {started_at}",
    ]
    if fallback_used:
        lines.append("")
        lines.append(
            "NOTE: started_at is approximated from the remote pid file's "
            "mtime (the original echo was lost during launch); it may be "
            "1-2 seconds later than the actual process start."
        )
    if desc_truncated:
        lines.append("[description truncated to 500 chars]")
    return "\n".join(lines)


def _bg_sftp_fallback(conn: SSHConnection, sid: str, id_: int):
    """Try to recover pid via SFTP read of remote pid file.

    Returns (pid, started_at_iso, started_at_unix, True, None) on success;
    (None, None, None, False, str(e)) on any failure (error_reason for B2 msg).
    """
    try:
        sftp = conn.get_sftp()
        remote_path = remote_pid_path(sid, id_)
        # Strip leading ~/ for paramiko (SFTP does not expand ~)
        sftp_path = remote_path[2:] if remote_path.startswith("~/") else remote_path
        attrs = sftp.stat(sftp_path)
        with sftp.open(sftp_path, "r") as f:
            content = f.read().decode("utf-8").strip()
        pid = int(content)
        ts = int(attrs.st_mtime)
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return pid, iso, ts, True, None
    except Exception as e:
        return None, None, None, False, str(e)
