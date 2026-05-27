"""Feedback tool. See spec §5.3.10."""
import json
import os
import pathlib
from datetime import datetime, timezone


def feedback(conn, feedback_path: str,
             category: str, summary: str, details: str = "") -> str:
    """
    Append a dev-loop feedback entry to a LOCAL JSONL file.

    The Feedback tool is the agent's channel for recording bugs and
    enhancement ideas about the remote-mcp tools themselves (NOT about
    the user's code or remote system). The maintainer reads this file
    when planning the next iteration.

    Output is purely local — nothing is transmitted anywhere. The agent
    is encouraged to use this tool non-blockingly: file an entry and
    continue the current task.

    Args:
        conn: SSHConnection (only `conn.config.name` is used — to attribute
            the entry to a specific host).
        feedback_path: local filesystem path to the JSONL file. Parent
            directory is auto-created if missing. Defaults to
            `~/.local/share/remote-mcp/feedback.jsonl` (set in config).
        category: one of `"bug"` or `"enhancement"`. Other values rejected.
        summary: one-line description. Must be non-empty.
        details: optional longer description (context, reproduction steps,
            proposed API for enhancements).

    Returns:
        `"Feedback recorded: [<category>] <summary> -> <path>"` on success.
        `"Error: category must be 'bug' or 'enhancement', got <x>"` on bad
        category.
        `"Error: summary cannot be empty"` on blank summary.
        Errors do NOT write to the file.

    Concurrency safety:
        A single `open(path, 'a').write(line)` of a short JSONL line is
        POSIX-atomic (line size << PIPE_BUF ~4 KB), so multiple per-host
        MCP server processes can append to the same file without locking.
    """
    if category not in ("bug", "enhancement"):
        return (
            f"Error: category must be 'bug' or 'enhancement', got {category!r}"
        )
    if not summary.strip():
        return "Error: summary cannot be empty"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": conn.config.name,
        "category": category,
        "summary": summary.strip(),
        "details": (details.strip() or None) if details else None,
        "session_pid": os.getpid(),
    }

    path = pathlib.Path(feedback_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    # JSONL append. Single write() of < PIPE_BUF (~4 KB on Linux) is POSIX-atomic
    # → multi-process append safe.
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)

    return f"Feedback recorded: [{category}] {summary} -> {feedback_path}"
