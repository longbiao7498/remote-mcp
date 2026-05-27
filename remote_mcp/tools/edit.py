"""Edit tool. See spec §5.3.3."""
from ..connection import SSHConnection


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
        `"Error: old_string found N times in <file_path>. Provide more
        context to match uniquely."` if N>1 and replace_all is False.
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
            return (
                f"Error: old_string found {count} times in {file_path}. "
                f"Provide more context to match uniquely."
            )
        new_content = content.replace(old_string, new_string, 1)

    with sftp.file(file_path, "w") as f:
        f.write(new_content.encode("utf-8"))
    return f"Successfully edited {file_path}"
