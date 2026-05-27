"""Write tool. See spec §5.3.2."""
import posixpath

from ..connection import SSHConnection


def _sftp_mkdirs(sftp, path: str) -> None:
    """Recursive mkdir via SFTP only (no shell)."""
    if path in ("", "/", "."):
        return
    try:
        sftp.stat(path)
        return  # exists
    except IOError:
        pass
    parent = posixpath.dirname(path)
    if parent and parent != path:
        _sftp_mkdirs(sftp, parent)
    try:
        sftp.mkdir(path)
    except IOError:
        # Race: someone else created it
        pass


def write(conn: SSHConnection, file_path: str, content: str) -> str:
    """
    Write content to a file on the remote host via SFTP.

    Creates parent directories as needed. For repeated writes to the same
    file, prefer consecutive Write calls (each is independent) or MultiEdit
    if you need to batch multiple changes.

    Args:
        conn: established SSHConnection.
        file_path: absolute path on the remote host.
        content: text content to write (UTF-8 encoded).

    Returns:
        `"Successfully wrote <N> characters to <file_path>"` on success.
        `"Error: <stderr>"` on write failures (e.g. permission denied).
    """
    sftp = conn.get_sftp()
    parent = posixpath.dirname(file_path)
    if parent:
        _sftp_mkdirs(sftp, parent)
    encoded = content.encode("utf-8")
    with sftp.file(file_path, "w") as f:
        f.write(encoded)
    return f"Successfully wrote {len(content)} characters to {file_path}"
