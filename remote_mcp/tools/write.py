"""Write tool. See spec §5.3.2."""
import posixpath

from ..connection import SSHConnection
from ..paths import resolve_path


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
        `"Error: Permission denied: <file_path>"` if the user can't write.
        `"Error: <message>"` for other SFTP failures (e.g. target is a
        directory, disk full, invalid path).
    """
    try:
        file_path = resolve_path(file_path, conn.config.cwd)
    except ValueError as e:
        return f"Error: {e}"

    sftp = conn.get_sftp()
    parent = posixpath.dirname(file_path)
    encoded = content.encode("utf-8")
    try:
        if parent:
            _sftp_mkdirs(sftp, parent)
        with sftp.file(file_path, "w") as f:
            f.write(encoded)
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except (IOError, OSError) as e:
        # paramiko maps SFTP errors to IOError/OSError. EACCES is wrapped as
        # IOError(errno=13) on some SFTP servers, so check that too.
        import errno as _errno
        if getattr(e, "errno", None) == _errno.EACCES:
            return f"Error: Permission denied: {file_path}"
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"
    return f"Successfully wrote {len(content)} characters to {file_path}"
