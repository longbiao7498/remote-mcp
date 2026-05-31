"""status.sh local source + remote cache management (spec §9)."""
import errno
from pathlib import Path

from ..connection import exec_with_snapshot, ExecResult
from .paths import (
    local_status_path, remote_status_path,
)


def _strip_tilde(path: str) -> str:
    """Strip leading '~/' for paramiko SFTP which doesn't expand ~.
    Falls back to literal path if no leading '~/'."""
    if path.startswith("~/"):
        return path[2:]
    return path


def set_status_script(conn, sid: str, host: str, id_: int,
                      script: str, timeout: int) -> None:
    """Write script body to local source and SFTP-upload to remote cache.

    Does NOT run the first-run validation — caller handles that separately
    so it can also handle the timeout-cleanup path.
    """
    # Local write
    local_path = local_status_path(sid, host, id_)
    local_path.write_text(script)
    # SFTP upload
    sftp = conn.get_sftp()
    remote_path = _strip_tilde(remote_status_path(sid, id_))
    with sftp.open(remote_path, "w") as f:
        f.write(script)


def clear_status_script(conn, sid: str, host: str, id_: int) -> None:
    """Delete local source. Leave remote cache (per spec §9.2.2)."""
    local_path = local_status_path(sid, host, id_)
    try:
        local_path.unlink()
    except FileNotFoundError:
        pass


def remove_status_script_fully(conn, sid: str, host: str, id_: int) -> None:
    """Delete BOTH local source and remote cache (used by first-run-timeout
    cleanup in spec §9.2.1 step 7)."""
    clear_status_script(conn, sid, host, id_)
    sftp = conn.get_sftp()
    remote_path = _strip_tilde(remote_status_path(sid, id_))
    try:
        sftp.remove(remote_path)
    except FileNotFoundError:
        pass
    except IOError:
        pass  # best-effort


def run_status_script(conn, sid: str, host: str, id_: int,
                      timeout: int) -> ExecResult:
    """Execute the status script on remote, with cache-miss recovery.

    1. SFTP stat remote cache; if missing, upload from local source
    2. Run remote script via exec_with_snapshot
    """
    sftp = conn.get_sftp()
    remote_path = _strip_tilde(remote_status_path(sid, id_))
    try:
        sftp.stat(remote_path)
    except IOError as e:
        if getattr(e, "errno", None) == errno.ENOENT or "No such file" in str(e):
            # Re-upload from local source
            local_path = local_status_path(sid, host, id_)
            script = local_path.read_text()
            with sftp.open(remote_path, "w") as f:
                f.write(script)
        else:
            raise

    # Run it (snapshot sourced via helper). Use tilde path so remote bash expands ~.
    cmd = f"bash --noprofile --norc {remote_status_path(sid, id_)}"
    return exec_with_snapshot(conn, cmd, timeout=float(timeout))
