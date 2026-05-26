"""Feedback tool. See spec §5.3.10."""
import json
import os
import pathlib
from datetime import datetime, timezone


def feedback(conn, feedback_path: str,
             category: str, summary: str, details: str = "") -> str:
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
