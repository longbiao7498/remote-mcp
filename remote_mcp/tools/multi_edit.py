"""MultiEdit tool. See spec §5.3.4."""
from typing import List, Dict, Tuple, Optional

from ..connection import SSHConnection
from .edit import _match_line_numbers


def apply_edits(content: str, edits: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply a sequence of edits atomically to file content.

    Each edit specifies old_string, new_string, and optionally replace_all.
    Edits are applied in order; if any edit fails, the entire operation aborts
    without modifying the original content. On success, returns the fully
    modified content.

    Args:
        content: the full file content as a string.
        edits: list of edit dicts, each with 'old_string', 'new_string',
            and optional 'replace_all' (default False).

    Returns:
        (modified_content, None) on success.
        (None, error_msg) on failure — error_msg begins with "Error: edit #N: ...".
    """
    current = content
    for i, e in enumerate(edits, start=1):
        old = e["old_string"]
        new = e["new_string"]
        replace_all = e.get("replace_all", False)
        if replace_all:
            if old not in current:
                return None, f"Error: edit #{i}: old_string not found"
            current = current.replace(old, new)
        else:
            count = current.count(old)
            if count == 0:
                return None, f"Error: edit #{i}: old_string not found"
            if count > 1:
                line_list = _match_line_numbers(current, old)
                return None, (
                    f"Error: edit #{i}: old_string found {count} times "
                    f"(lines {line_list}). "
                    f"Provide more context or set replace_all=true."
                )
            current = current.replace(old, new, 1)
    return current, None


def multi_edit(conn: SSHConnection, file_path: str,
               edits: List[Dict]) -> str:
    """
    Apply multiple edits to a single file via a single SFTP read-write cycle.

    Reads the file once, applies all edits in sequence, and writes back.
    More efficient than calling Edit multiple times. Failures are atomic —
    if any edit fails, the file is unchanged.

    Args:
        conn: established SSHConnection.
        file_path: absolute path on the remote host.
        edits: list of edit dicts. Each has 'old_string', 'new_string',
            and optional 'replace_all' (default False, meaning exact uniqueness
            required unless replace_all=True).

    Returns:
        `"Successfully applied <N> edits to <file_path>"` on success.
        `"Error: File not found: <file_path>"` if the file doesn't exist.
        `"Error: edits list is empty"` if edits is [].
        `"Error: edit #N: old_string not found"` if edit N's old_string
            doesn't match the (partially-modified) content.
        `"Error: edit #N: old_string found M times. Provide more context or
            set replace_all=true."` if replace_all is False and the match is
            ambiguous.
    """
    if not edits:
        return "Error: edits list is empty"
    sftp = conn.get_sftp()
    try:
        with sftp.file(file_path, "r") as f:
            content = f.read().decode("utf-8")
    except IOError:
        return f"Error: File not found: {file_path}"

    new_content, err = apply_edits(content, edits)
    if err:
        return err

    with sftp.file(file_path, "w") as f:
        f.write(new_content.encode("utf-8"))
    return f"Successfully applied {len(edits)} edits to {file_path}"
