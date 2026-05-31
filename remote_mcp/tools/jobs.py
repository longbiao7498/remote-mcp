"""Jobs tool — panel query (spec §8)."""
import json
import time

from ..connection import exec_with_snapshot
from ..jobs.sid import derive_sid
from ..jobs.meta import (
    list_active_metas,
    list_zombie_metas,
    find_meta_by_id_anywhere,
    find_meta_by_name_anywhere,
    write_state,
)
from ..jobs.state import (
    derive_state,
    build_batched_kill_check,
    parse_batched_kill_output,
)
from ..jobs.scripts import run_status_script
from ..jobs.constants import KILL_FAIL_PER_TASK_THRESHOLD


def jobs_tool(conn, name: str = None, id: int = None,
              filter: str = None) -> str:
    """Query the background task panel (spec §8).

    List mode: Jobs() / Jobs(filter=...)
    Single mode: Jobs(name=X) / Jobs(id=N)
    """
    host = conn.config.name
    sid, _ = derive_sid()

    # Param validation
    if name is not None and id is not None:
        return "Error: provide only one of name or id"
    if (name is not None or id is not None) and filter is not None:
        return "Error: filter is for list mode; do not combine with name or id"

    if name is not None or id is not None:
        return _single_mode(conn, sid, host, name, id)
    return _list_mode(conn, sid, host, filter)


def _list_mode(conn, sid: str, host: str, filter: str | None) -> str:
    """List mode: scan dir, batch kill -0 for non-terminal tasks, write back."""
    # Step 1+2: read metas from the correct directory
    if filter == "zombies":
        metas = list_zombie_metas(sid, host)
        location = "zombie"
    else:
        metas = list_active_metas(sid, host)
        location = "active"

    # Step 3: pre-filter (filter logic that doesn't need remote observation)
    if filter == "stuck_kill":
        metas = [
            m for m in metas
            if m.get("state") == "kill_failed"
            and len(m.get("kill_attempts", [])) >= KILL_FAIL_PER_TASK_THRESHOLD
        ]
    # stopped_unprocessed filter is applied AFTER state refresh (step 6)
    # zombies filter already handled by directory choice above

    # Step 4+5: batched kill -0 for non-terminal tasks only
    # Spec §7.1: only state ∈ {running, kill_failed} need observation
    pids_to_observe = [
        m["pid"] for m in metas
        if m.get("pid") is not None
        and m.get("state") in ("running", "kill_failed")
    ]

    if pids_to_observe:
        cmd = build_batched_kill_check(pids_to_observe)
        try:
            r = exec_with_snapshot(conn, cmd, timeout=conn.config.op_timeout_default)
        except Exception as e:
            raise type(e)(f"observing pids in Jobs list on {host}: {e}") from e
        if r.timed_out:
            raise TimeoutError(f"Jobs(list) batched kill check on {host} timed out")
        now_unix, alive_map = parse_batched_kill_output(r.stdout)
    else:
        now_unix = int(time.time())
        alive_map = {}

    # Step 6+7: update state for observed tasks (only those with pid in alive_map)
    for m in metas:
        pid = m.get("pid")
        if pid in alive_map:
            new_state = derive_state(
                alive=alive_map[pid],
                kill_requested=m.get("kill_requested_at_unix") is not None,
            )
            m["state"] = new_state
            m["state_at_unix"] = now_unix
            write_state(sid, host, m["id"], new_state, now_unix, in_dir=location)

    # Apply stopped_unprocessed filter after state refresh
    if filter == "stopped_unprocessed":
        metas = [m for m in metas if m.get("state") in ("stopped", "killed")]

    # Step 8: assemble return
    items = [_list_item(m, now_unix) for m in metas]

    if filter == "zombies":
        header = f"{len(items)} zombie jobs"
    else:
        header = f"{len(items)} active jobs (filter={filter or 'none'})"

    out = f"{header}:\n\n{json.dumps(items, indent=2)}"
    return out


def _list_item(m: dict, now_unix: int) -> dict:
    """Build a list-mode entry per spec §8.3."""
    started = m.get("started_at_unix") or now_unix
    elapsed = max(0, now_unix - started)
    return {
        "id": m["id"],
        "name": m["name"],
        "description": m.get("description", ""),
        "host": m["host"],
        "pid": m.get("pid"),
        "log_path": m["log_path"],
        "state": m.get("state"),
        "started_at": m.get("started_at"),
        "elapsed_sec": elapsed,
        "kill_requested_at": m.get("kill_requested_at"),
        "kill_attempts_count": len(m.get("kill_attempts", [])),
        "zombie": m.get("zombie", False),
    }


def _single_mode(conn, sid: str, host: str,
                 name: str | None, id_: int | None) -> str:
    """Single-task mode: locate → kill -0 if non-terminal → status.sh."""
    # Step 1: locate (active → archive → zombie)
    if id_ is not None:
        meta, location = find_meta_by_id_anywhere(sid, host, id_)
        ref = f"id={id_}"
    else:
        meta, location = find_meta_by_name_anywhere(sid, host, name)
        ref = f"name='{name}'"

    if meta is None:
        return f"Error: no job with {ref} in current session+host panel"

    # Step 2: pid check
    pid = meta.get("pid")
    if pid is None:
        return (
            f"Error: task '{meta.get('name')}' meta is corrupted (pid missing); "
            f"investigate ~/.local/share/remote-mcp/jobpane/{sid}/{host}/"
            f"{meta['id']}-meta.json manually"
        )

    now_unix = int(time.time())

    # Step 3: kill -0 only if state is non-terminal (§7.1)
    if meta.get("state") in ("running", "kill_failed"):
        cmd = build_batched_kill_check([pid])
        try:
            r = exec_with_snapshot(conn, cmd, timeout=conn.config.op_timeout_default)
        except Exception as e:
            raise type(e)(f"observing pid for {ref} on {host}: {e}") from e
        if r.timed_out:
            raise TimeoutError(f"Jobs single-task kill check on {host} timed out")
        nu, am = parse_batched_kill_output(r.stdout)
        if nu:
            now_unix = nu
        new_state = derive_state(
            alive=am.get(pid, False),
            kill_requested=meta.get("kill_requested_at_unix") is not None,
        )
        meta["state"] = new_state
        meta["state_at_unix"] = now_unix
        write_state(sid, host, meta["id"], new_state, now_unix, in_dir=location)

    # Step 4: status.sh — runs REGARDLESS of state (§7.1 + §8.5 step 4)
    script_output = None
    if meta.get("script_timeout") is not None:
        try:
            sr = run_status_script(conn, sid, host, meta["id"],
                                   timeout=meta["script_timeout"])
            script_output = {
                "stdout": sr.stdout,
                "stderr": sr.stderr,
                "exit_code": None if sr.timed_out else sr.exit_code,
                "elapsed_sec": sr.elapsed_sec,
                "error": (
                    f"status script timed out after {meta['script_timeout']}s "
                    f"(SIGHUP sent to script; remote effects may have started)"
                    if sr.timed_out else None
                ),
            }
        except Exception as e:
            script_output = {
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "elapsed_sec": 0,
                "error": f"exec failed: {e}",
            }

    # Step 5: assemble single-task return (spec §8.4)
    started = meta.get("started_at_unix") or now_unix
    elapsed = max(0, now_unix - started)
    payload = {
        "id": meta["id"],
        "name": meta["name"],
        "description": meta.get("description", ""),
        "command": meta["command"],
        "log_path": meta["log_path"],
        "host": meta["host"],
        "pid": pid,
        "state": meta.get("state"),
        "started_at": meta.get("started_at"),
        "elapsed_sec": elapsed,
        "kill_requested_at": meta.get("kill_requested_at"),
        "kill_attempts": meta.get("kill_attempts", []),
        "archived_at": meta.get("archived_at"),
        "zombie": meta.get("zombie", False),
        "status_script_output": script_output,
    }
    return json.dumps(payload, indent=2)
