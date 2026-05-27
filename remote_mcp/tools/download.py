"""Download tool. Pull a remote file to local via SFTP.

For Linux/macOS users: prefer Bash + scp/rsync with run_in_background=true.
This tool is primarily for Windows users without scp in PATH.
"""
import errno as _errno
import os
import stat as _stat

from ..connection import SSHConnection


def download(conn: SSHConnection, remote_path: str, local_path: str) -> str:
    """
    Pull a remote file to the LOCAL machine via SFTP.

    Args:
        conn: established SSHConnection.
        remote_path: absolute path on the remote host.
        local_path: absolute path on the local machine. `~` is expanded.
            Parent directory must exist (we don't auto-create local dirs).
            Overwrites if exists.

    Returns:
        `"Successfully downloaded <N> bytes from <remote_path> to <local_path>"` on success.
        `"Error: Remote file not found: <remote_path>"` if remote doesn't exist.
        `"Error: Remote path is a directory, not a file: <remote_path>"` if remote is a dir.
        `"Error: File too large for Download: <N> bytes exceeds transfer_size_cap
            (<cap> bytes). ..."` if remote file size > conn.config.transfer_size_cap.
            Error includes a ready-to-paste `Bash("scp ...", run_in_background=true)`
            template.
        `"Error: Local parent directory not found: <dir>"` if dirname(local_path)
            doesn't exist.
        `"Error: Permission denied: <local_path>"` if local write is denied.
        `"Error: <message>"` for other SFTP errors.
    """
    local = os.path.expanduser(local_path)
    local_parent = os.path.dirname(local) or "."
    if not os.path.isdir(local_parent):
        return f"Error: Local parent directory not found: {local_parent}"

    sftp = conn.get_sftp()
    # Stat remote to check existence, type, and size before transfer.
    try:
        st = sftp.stat(remote_path)
    except IOError:
        return f"Error: Remote file not found: {remote_path}"

    if _stat.S_ISDIR(st.st_mode or 0):
        return f"Error: Remote path is a directory, not a file: {remote_path}"

    size = st.st_size
    cap = conn.config.transfer_size_cap
    if size > cap:
        scp_template = (
            f"Bash(command=\"scp {conn.config.user}@{conn.config.hostname}:"
            f"{remote_path} {local_path}\", run_in_background=true)"
        )
        return (
            f"Error: File too large for Download: {size} bytes exceeds "
            f"transfer_size_cap ({cap} bytes). For files this size, the "
            f"right tool is Bash with scp or rsync: {scp_template}. It runs "
            f"in background, handles any size, and supports resume."
        )

    try:
        sftp.get(remote_path, local)
    except PermissionError:
        return f"Error: Permission denied: {local_path}"
    except (IOError, OSError) as e:
        if getattr(e, "errno", None) == _errno.EACCES:
            return f"Error: Permission denied: {local_path}"
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"

    return f"Successfully downloaded {size} bytes from {remote_path} to {local_path}"
