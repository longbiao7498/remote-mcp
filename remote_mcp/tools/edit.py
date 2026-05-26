"""Edit tool. See spec §5.3.3."""
from ..connection import SSHConnection


def edit(conn: SSHConnection, file_path: str,
         old_string: str, new_string: str,
         replace_all: bool = False) -> str:
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
