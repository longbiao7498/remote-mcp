"""JobKill tool — single kill attempt + L1/L2 warnings (spec §10)."""
import re
import time
from datetime import datetime, timezone

from ..connection import exec_with_snapshot
from ..jobs.sid import derive_sid
from ..jobs.meta import (
    find_meta_by_name_anywhere, find_meta_by_id_anywhere, write_meta,
    list_active_metas,
)
from ..jobs.constants import (
    KILL_FAIL_PER_TASK_THRESHOLD, STUCK_KILL_WARN_THRESHOLD,
)


def job_kill_tool(conn, name: str = None, id: int = None,
                  kill_cmd: str = None) -> str:
    host = conn.config.name
    sid, _ = derive_sid()

    if name is not None and id is not None:
        return "Error: provide only one of name or id"
    if id is not None:
        meta, location = find_meta_by_id_anywhere(sid, host, id)
        display = meta.get("name") if meta else f"id={id}"
    elif name is not None:
        meta, location = find_meta_by_name_anywhere(sid, host, name)
        display = name
    else:
        return "Error: provide name or id"

    if meta is None:
        ref = f"name='{name}'" if name else f"id={id}"
        return f"Error: no job with {ref} in current session+host panel"
    if location != "active":
        return (
            f"Error: cannot kill job '{display}' — it is in archive or zombie "
            f"queue (no longer under panel management). For zombie tasks the "
            f"process may still be running on remote; investigate with Bash if needed."
        )

    pid = meta.get("pid")
    if pid is None:
        return f"Error: task '{display}' meta is corrupted (pid missing)"

    # Write kill_requested_at BEFORE exec (spec §14 C5)
    now_unix = int(time.time())
    iso = datetime.fromtimestamp(now_unix, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    meta["kill_requested_at"] = iso
    meta["kill_requested_at_unix"] = now_unix
    write_meta(sid, host, meta)

    # Packed exec: kill + kill -0 in one round trip (spec §10.2 step 3)
    actual_kill_cmd = kill_cmd if kill_cmd is not None else f"kill -TERM -- -{pid}"
    packed = (
        f"{actual_kill_cmd}\n"
        f"KE=$?\n"
        f"sleep 0.1\n"
        f"kill -0 {pid} 2>/dev/null\n"
        f"AE=$?\n"
        f'echo "KILL_EXIT=$KE"\n'
        f'echo "ALIVE_EXIT=$AE"'
    )
    try:
        r = exec_with_snapshot(conn, packed, timeout=5.0)
    except Exception as e:
        return (
            f"Error: kill command did not respond within 5s on {host}. "
            f"kill_requested_at has been recorded; state was not updated this call. "
            f"Run Jobs(name='{display}') to refresh; if state becomes 'killed' "
            f"the process died after timeout; if state remains 'running' or "
            f"'kill_failed', the kill command may have failed to take effect. "
            f"({e})"
        )
    if r.timed_out:
        return (
            f"Error: kill command did not respond within 5s on {host}. "
            f"kill_requested_at has been recorded; state was not updated this call. "
            f"Run Jobs(name='{display}') to refresh; if state becomes 'killed' "
            f"the process died after timeout; if state remains 'running' or "
            f"'kill_failed', the kill command may have failed to take effect."
        )

    km = re.search(r"KILL_EXIT=(-?\d+)", r.stdout)
    am = re.search(r"ALIVE_EXIT=(-?\d+)", r.stdout)
    kill_exit = int(km.group(1)) if km else -1
    alive_exit = int(am.group(1)) if am else -1
    alive = (alive_exit == 0)

    # Append to kill_attempts (spec §10.2 step 4)
    meta["kill_attempts"].append({
        "at": iso, "at_unix": now_unix,
        "kill_cmd": actual_kill_cmd,
        "exit_code": kill_exit,
        "stdout": r.stdout, "stderr": r.stderr,
    })
    # Derive + write state (spec §10.2 step 5)
    new_state = "kill_failed" if alive else "killed"
    meta["state"] = new_state
    meta["state_at_unix"] = now_unix
    write_meta(sid, host, meta)

    attempts_n = len(meta["kill_attempts"])
    lines = [
        f"Kill requested for '{display}' (id={meta['id']}).",
        f"  kill_command: {actual_kill_cmd}",
        f"  command_exit_code: {kill_exit}",
        f"  kill_requested_at: {iso}",
        f"  kill_attempts_count: {attempts_n}",
        f"  state_now: {new_state}",
        "",
    ]
    if new_state == "killed":
        lines.append(
            f"Verify with Jobs(name=\"{display}\") — state is already 'killed' in meta. "
            f"If state stays 'kill_failed' after multiple retries, consider "
            f"JobArchive(name='{display}', as_zombie=True) to give up."
        )
    else:
        lines.append(
            f"Verify with Jobs(name=\"{display}\") — state will reflect "
            f"{new_state} based on current observation."
        )

    # L1: single-task warning (spec §10.3.1)
    if alive and attempts_n >= KILL_FAIL_PER_TASK_THRESHOLD:
        lines.append("")
        lines.append(
            f"NOTE: this task has {attempts_n} failed kill attempts now. If the "
            f"process resists further signals, try `kill -KILL -- -{pid}`, "
            f"`scancel --signal=KILL`, or runtime-specific shutdown commands. "
            f"After exhausting retries, give up via JobArchive(name='{display}', "
            f"as_zombie=True) to move it to the zombie queue (it will keep "
            f"running on remote unmanaged)."
        )

        # L2: host-level aggregated warning (spec §10.3.2)
        stuck_count = sum(
            1 for m in list_active_metas(sid, host)
            if m.get("state") == "kill_failed"
            and len(m.get("kill_attempts", [])) >= KILL_FAIL_PER_TASK_THRESHOLD
        )
        if stuck_count >= STUCK_KILL_WARN_THRESHOLD:
            lines.extend([
                "",
                "==================================================================",
                f"WARNING: {host} has {stuck_count} jobs with persistent kill failures.",
                "==================================================================",
                "",
                "These are tasks where the panel issued kill but the process keeps",
                "running. Pattern of failure across multiple tasks suggests:",
                "  - your kill_cmd choices may be inappropriate (wrong signal / wrong",
                "    PID / missing setsid in launch); inspect kill_attempts arrays",
                "    via Jobs(name=...) to compare what you tried",
                "  - or the remote host may have signal-resistant processes (D-state",
                "    IO, kernel issues, sudoed root)",
                "",
                "Consider pausing automation and investigating before more launches.",
                "List affected tasks: Jobs(filter='stuck_kill').",
            ])

    return "\n".join(lines)
