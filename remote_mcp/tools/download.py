"""Download tool. Pull a remote file to local via SFTP.

For Linux/macOS users: prefer Bash + scp/rsync with run_in_background=true.
This tool is primarily for Windows users without scp in PATH.
"""
import errno as _errno
import os
import stat as _stat

from ..connection import SSHConnection
from ..paths import resolve_path


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

    Note on partial files:
        If the transfer fails mid-stream (network drop, remote dies during
        get), paramiko may leave a partial file at `local_path`. We do NOT
        auto-delete it, because if `local_path` existed before the call we'd
        be destroying the user's existing file on a transient failure. The
        caller should check the returned status; on `Error:`, treat the local
        target as potentially-corrupt and re-fetch (or use scp/rsync with
        `--partial --inplace` for resumable transfers).
    """
    local = os.path.expanduser(local_path)
    local_parent = os.path.dirname(local) or "."
    if not os.path.isdir(local_parent):
        return f"Error: Local parent directory not found: {local_parent}"

    try:
        remote_path = resolve_path(remote_path, conn.config.cwd)
    except ValueError as e:
        return f"Error: {e}"

    sftp = conn.get_sftp()
    # Stat remote to check existence, type, and size before transfer.
    try:
        st = sftp.stat(remote_path)
    except IOError:
        return f"Error: Remote file not found: {remote_path}"

    if _stat.S_ISDIR(st.st_mode or 0):
        return f"Error: Remote path is a directory, not a file: {remote_path}"

    # st.st_size can be None for special files (pipes, sockets, /proc entries
    # that pass the S_ISDIR check but aren't regular files). Treat None as 0 —
    # the transfer is unlikely to be huge, and avoiding a TypeError keeps the
    # tool's "never raises, always returns Error: ..." contract intact.
    size = st.st_size or 0
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
