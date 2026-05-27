"""Upload tool. Push a local file to the remote via SFTP.

For Linux/macOS users: prefer Bash + scp/rsync with run_in_background=true
— non-blocking, no size limit, supports resume. This tool is primarily
for Windows users without scp in PATH.
"""
import errno as _errno
import os
import posixpath

from ..connection import SSHConnection


def upload(conn: SSHConnection, local_path: str, remote_path: str) -> str:
    """
    Push a local file to the remote host via SFTP.

    Args:
        conn: established SSHConnection.
        local_path: absolute path on the LOCAL machine (where the MCP
            server runs). `~` is expanded.
        remote_path: absolute path on the remote host. Overwrites if exists.

    Returns:
        `"Successfully uploaded <N> bytes from <local_path> to <remote_path>"` on success.
        `"Error: Local file not found: <local_path>"` if local doesn't exist.
        `"Error: Local path is a directory, not a file: <local_path>"` if local is a dir.
        `"Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). ..."`
            if local file size > conn.config.transfer_size_cap. The error message
            includes a ready-to-paste `Bash("scp ...", run_in_background=true)` template.
        `"Error: Permission denied: <remote_path>"` if remote write is denied.
        `"Error: <message>"` for other SFTP errors.
    """
    local = os.path.expanduser(local_path)

    if not os.path.exists(local):
        return f"Error: Local file not found: {local_path}"
    if os.path.isdir(local):
        return f"Error: Local path is a directory, not a file: {local_path}"

    size = os.path.getsize(local)
    cap = conn.config.transfer_size_cap
    if size > cap:
        scp_template = (
            f"Bash(command=\"scp {local_path} {conn.config.user}@"
            f"{conn.config.hostname}:{remote_path}\", run_in_background=true)"
        )
        return (
            f"Error: File too large for Upload: {size} bytes exceeds "
            f"transfer_size_cap ({cap} bytes). For files this size, the "
            f"right tool is Bash with scp or rsync: {scp_template}. It runs "
            f"in background, handles any size, and supports resume."
        )

    sftp = conn.get_sftp()
    # Ensure parent dir exists on remote (matches Write's behavior)
    parent = posixpath.dirname(remote_path)
    try:
        if parent:
            from .write import _sftp_mkdirs
            _sftp_mkdirs(sftp, parent)
        sftp.put(local, remote_path)
    except PermissionError:
        return f"Error: Permission denied: {remote_path}"
    except (IOError, OSError) as e:
        if getattr(e, "errno", None) == _errno.EACCES:
            return f"Error: Permission denied: {remote_path}"
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"

    return f"Successfully uploaded {size} bytes from {local_path} to {remote_path}"
