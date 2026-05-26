"""MultiEdit tool. See spec §5.3.4."""
from typing import List, Dict, Tuple, Optional

from ..connection import SSHConnection


def apply_edits(content: str, edits: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply edits sequentially. Atomic: any failure returns (None, error_msg).
    Returns (new_content, None) on success.
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
                return None, (
                    f"Error: edit #{i}: old_string found {count} times. "
                    f"Provide more context or set replace_all=true."
                )
            current = current.replace(old, new, 1)
    return current, None


def multi_edit(conn: SSHConnection, file_path: str,
               edits: List[Dict]) -> str:
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
