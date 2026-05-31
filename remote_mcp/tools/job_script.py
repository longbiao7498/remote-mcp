"""JobScript tool — attach/clear status script (spec §9)."""
from ..jobs.sid import derive_sid
from ..jobs.meta import (
    find_meta_by_name_anywhere, find_meta_by_id_anywhere, write_meta,
)
from ..jobs.scripts import (
    set_status_script, clear_status_script, remove_status_script_fully,
    run_status_script,
)


def job_script_tool(conn, name: str = None, id: int = None,
                    script: str = "", timeout: int = None) -> str:
    host = conn.config.name
    sid, _ = derive_sid()
    if timeout is None:
        return "Error: timeout is required"

    # Locate task (active only — script ops don't make sense on archived)
    if name is not None and id is not None:
        return "Error: provide only one of name or id"
    if id is not None:
        meta, location = find_meta_by_id_anywhere(sid, host, id)
        ref = f"id={id}"
        display_name = meta.get("name") if meta else f"id={id}"
    elif name is not None:
        meta, location = find_meta_by_name_anywhere(sid, host, name)
        ref = f"name='{name}'"
        display_name = name
    else:
        return "Error: provide name or id"

    if meta is None:
        return f"Error: no job with {ref} in current session+host panel"
    if location != "active":
        return (
            f"Error: cannot attach status script to archived/zombie job "
            f"'{display_name}'"
        )

    id_ = meta["id"]

    # Clear path
    if script == "":
        clear_status_script(conn, sid, host, id_)
        meta["script_timeout"] = None
        write_meta(sid, host, meta)
        return (
            f"Status script cleared for '{display_name}' (id={id_}).\n"
            f"(Remote cache file at ~/.cache/remote-mcp-{sid}-{id_}-status.sh "
            f"is left in place but no longer referenced; it will be overwritten "
            f"if you attach a new script.)"
        )

    # Set path: write local + SFTP upload
    set_status_script(conn, sid, host, id_, script)

    # First-run validation
    try:
        result = run_status_script(conn, sid, host, id_, timeout=timeout)
    except Exception as e:
        # SSH error — remove what we just wrote
        remove_status_script_fully(conn, sid, host, id_)
        meta["script_timeout"] = None
        write_meta(sid, host, meta)
        return (
            f"Error: status script first-run on {host} failed: {e}. "
            f"Script has been removed; status script for '{display_name}' is now empty."
        )

    if result.timed_out:
        remove_status_script_fully(conn, sid, host, id_)
        meta["script_timeout"] = None
        write_meta(sid, host, meta)
        return (
            f"Error: status script first-run timed out after {timeout}s on {host}. "
            f"Script has been removed (both local source and remote cache); "
            f"status script for '{display_name}' is now empty. Likely causes: "
            f"script logic too slow, or timeout too tight. Adjust and call "
            f"JobScript again."
        )

    # Accept regardless of exit code
    meta["script_timeout"] = timeout
    write_meta(sid, host, meta)

    note = ""
    if result.exit_code != 0:
        note = (
            f" NOTE: first-run exited with non-zero code. The script is still "
            f"attached (non-zero exit may be intentional, e.g. 'task not yet "
            f"in expected phase'). Verify the output below matches your intent; "
            f"call JobScript again with the same name to replace."
        )

    stdout_lines = result.stdout.splitlines() if result.stdout else []
    stderr_lines = result.stderr.splitlines() if result.stderr else []

    stdout_block = (
        "\n".join(f"    {line}" for line in stdout_lines)
        if stdout_lines else "    (empty)"
    )
    stderr_block = (
        "  stderr: (empty)"
        if not result.stderr
        else "  stderr: |\n" + "\n".join(f"    {line}" for line in stderr_lines)
    )

    return (
        f"Status script attached to '{display_name}' (id={id_}).{note}\n"
        f"First-run validation:\n"
        f"  exit_code: {result.exit_code}\n"
        f"  elapsed_sec: {result.elapsed_sec:.2f}\n"
        f"  stdout: |\n"
        f"{stdout_block}\n"
        f"{stderr_block}"
    )
