"""Edit tool. See spec §5.3.3."""
from ..connection import SSHConnection


def _match_line_numbers(content: str, old_string: str, cap: int = 10) -> str:
    """
    Return a comma-separated string of 1-based line numbers where
    `old_string` occurs in `content` (non-overlapping). If there are
    more than `cap` occurrences, list the first `cap` then append
    `, ... +N more`.

    Used in the "found N times" error so the agent can pick which match
    to disambiguate without a follow-up Grep.
    """
    if not old_string:
        return ""
    # Precompute line start offsets so we can map char offset → line number.
    line_start_offsets = [0]
    for i, c in enumerate(content):
        if c == "\n":
            line_start_offsets.append(i + 1)

    def line_of(offset: int) -> int:
        # Linear scan — sufficient for typical file sizes; bisect would
        # only matter for very large files which Edit isn't designed for.
        lineno = 1
        for ls in line_start_offsets[1:]:
            if ls > offset:
                return lineno
            lineno += 1
        return lineno

    lines = []
    idx = 0
    while True:
        pos = content.find(old_string, idx)
        if pos == -1:
            break
        lines.append(line_of(pos))
        idx = pos + len(old_string)  # non-overlapping

    if len(lines) <= cap:
        return ", ".join(str(l) for l in lines)
    return ", ".join(str(l) for l in lines[:cap]) + f", ... +{len(lines) - cap} more"


def edit(conn: SSHConnection, file_path: str,
         old_string: str, new_string: str,
         replace_all: bool = False) -> str:
    """
    Read-modify-write a single file via SFTP, replacing `old_string` with
    `new_string`.

    By default `old_string` must appear EXACTLY ONCE in the file — this
    matches Claude Code's native Edit semantics and forces the agent to
    provide enough context for an unambiguous match.

    For multiple changes to the same file, use MultiEdit instead — it
    reads/writes the file only once for any number of edits.

    Args:
        conn: established SSHConnection.
        file_path: absolute path on the remote host.
        old_string: the exact substring to replace.
        new_string: the replacement substring.
        replace_all: if True, replaces all occurrences (no uniqueness check).

    Returns:
        `"Successfully edited <file_path>"` on success.
        `"Error: File not found: <file_path>"` if the file doesn't exist.
        `"Error: old_string not found in <file_path>"` if no match.
        `"Error: old_string found N times in <file_path> (lines L1, L2, ...).
        Provide more context to match uniquely, or set replace_all=true to
        replace all."` if N>1 and replace_all is False. Line numbers are
        capped at the first 10; if more, suffix is "... +K more".
        Errors leave the file unchanged.
    """
    sftp = conn.get_sftp()
    try:
        with sftp.file(file_path, "r") as f:
            content = f.read().decode("utf-8")
    except IOError:
        return f"Error: File not found: {file_path}"

    if replace_all:
        if old_string not in content:
            return f"Error: old_string not found in {file_path}"
        new_content = content.replace(old_string, new_string)
    else:
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1:
            line_list = _match_line_numbers(content, old_string)
            return (
                f"Error: old_string found {count} times in {file_path} "
                f"(lines {line_list}). "
                f"Provide more context to match uniquely, "
                f"or set replace_all=true to replace all."
            )
        new_content = content.replace(old_string, new_string, 1)

    with sftp.file(file_path, "w") as f:
        f.write(new_content.encode("utf-8"))
    return f"Successfully edited {file_path}"
