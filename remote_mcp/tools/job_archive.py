"""JobArchive tool — pure-local archival + zombie path (spec §11)."""
import time
from datetime import datetime, timezone

from ..jobs.sid import derive_sid
from ..jobs.meta import (
    find_meta_by_name_anywhere, find_meta_by_id_anywhere,
    list_zombie_metas, write_meta, move_to_archive, move_to_zombie,
)
from ..jobs.constants import ZOMBIE_WARN_THRESHOLD


def job_archive_tool(conn, name: str = None, id: int = None,
                     as_zombie: bool = False) -> str:
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
        return f"Error: job '{display}' is already archived"

    state = meta.get("state")
    ts = meta.get("state_at_unix")

    # Branch by state
    if as_zombie:
        if state != "kill_failed":
            return (
                f"Error: as_zombie=True requires state=kill_failed; this task "
                f"is '{state}' — use plain JobArchive(name='{display}')"
            )
    else:
        if state == "running":
            return (
                f"Error: task '{display}' is in state 'running' per panel "
                f"(last observed at {ts}). Archive is for tasks you have "
                f"processed the results of. If you believe the task may have "
                f"finished: call Jobs(name='{display}') to refresh state, "
                f"then Read(log_path) to review results, then archive."
            )
        if state == "kill_failed":
            return (
                f"Error: cannot archive task '{display}' in state 'kill_failed' "
                f"(pid={meta.get('pid')}, kill_attempts={len(meta.get('kill_attempts', []))}). "
                f"Either: call JobKill(name='{display}') again to retry (try "
                f"kill_cmd='kill -KILL -- -{meta.get('pid')}' or runtime-specific "
                f"commands), or give up via JobArchive(name='{display}', "
                f"as_zombie=True) to move it to the zombie queue."
            )
        if state not in ("stopped", "killed"):
            return f"Error: task '{display}' has unexpected state '{state}'"

    # Accept: write archived_at + zombie flag, then move
    now_unix = int(time.time())
    iso = datetime.fromtimestamp(now_unix, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    meta["archived_at"] = iso
    meta["archived_at_unix"] = now_unix
    if as_zombie:
        meta["zombie"] = True
    write_meta(sid, host, meta)

    if as_zombie:
        move_to_zombie(sid, host, meta["id"])
    else:
        move_to_archive(sid, host, meta["id"])

    # Assemble return string
    lines = []
    if as_zombie:
        lines.append(f"Archived '{display}' (id={meta['id']}) as ZOMBIE.")
        lines.append(f"  archived_at: {iso}")
        lines.append(f"  kill_attempts: {len(meta.get('kill_attempts', []))} (see Jobs(id={meta['id']}) for details)")
        lines.append(f"  log_path: {meta['log_path']}    (still readable)")
        lines.append("")
        lines.append(
            f"The process may still be running on {host} outside panel management. "
            f"Investigate manually via Bash if its results matter."
        )

        # Count zombies on this host (after the move, so this task is included)
        zombie_count = len(list_zombie_metas(sid, host))
        lines.append("")
        lines.append(f"Zombie count on {host} is now {zombie_count}.")
        if zombie_count >= ZOMBIE_WARN_THRESHOLD:
            lines.extend([
                "",
                "==================================================================",
                f"ESCALATION WARNING: zombie count on {host} is now {zombie_count} (>= threshold).",
                "==================================================================",
                "",
                "Possible causes (review BEFORE assuming remote server is broken):",
                "",
                "1. Recent zombie tasks may share a root cause — inspect their",
                "   attempt histories with Jobs(filter='zombies') and Jobs(id=N) for",
                "   each. If they all failed the same kill command, the issue may be",
                "   in your kill_cmd choice (e.g. wrong PID, missing setsid, wrong",
                "   signal for the runtime).",
                "2. If kill_cmd exit codes were all 0 but processes still alive, the",
                "   remote process is genuinely refusing to die — possibly stuck in",
                "   uninterruptible IO (D state), kernel bug, or sudoed root process",
                "   you can't signal as your user.",
                "3. Only after ruling out the above: remote server may be unhealthy.",
                "",
                f"RECOMMENDED: stop the current task loop and SSH into {host} manually",
                "to investigate. Continued operation may produce more zombies.",
            ])
    else:
        lines.append(f"Archived '{display}' (id={meta['id']}).")
        lines.append(f"  archived_at: {iso}")
        lines.append(f"  log_path: {meta['log_path']}    (still readable)")
        lines.append("")
        lines.append(
            f"This name is now free for reuse by new launches (which will get a new id). "
            f"The old task's meta has been moved to .../archive/{meta['id']}-meta.json "
            f"and remains queryable via Jobs(id={meta['id']})."
        )

    return "\n".join(lines)
