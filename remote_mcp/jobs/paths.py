"""Local and remote path helpers for the job panel (spec §4)."""
import os
from pathlib import Path


def _xdg_data_home() -> Path:
    """Honor $XDG_DATA_HOME, default ~/.local/share/."""
    env = os.environ.get("XDG_DATA_HOME", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".local" / "share"


def local_jobpane_root() -> Path:
    """~/.local/share/remote-mcp/jobpane/ (or $XDG_DATA_HOME equivalent)."""
    return _xdg_data_home() / "remote-mcp" / "jobpane"


def local_sid_host_dir(sid: str, host: str) -> Path:
    return local_jobpane_root() / sid / host


def local_archive_dir(sid: str, host: str) -> Path:
    return local_sid_host_dir(sid, host) / "archive"


def local_zombie_dir(sid: str, host: str) -> Path:
    return local_sid_host_dir(sid, host) / "zombie"


def local_meta_path(sid: str, host: str, id_: int) -> Path:
    return local_sid_host_dir(sid, host) / f"{id_}-meta.json"


def local_status_path(sid: str, host: str, id_: int) -> Path:
    return local_sid_host_dir(sid, host) / f"{id_}-status.sh"


def local_next_id_path(sid: str, host: str) -> Path:
    return local_sid_host_dir(sid, host) / "next_id"


def local_id_lock_path(sid: str, host: str) -> Path:
    return local_sid_host_dir(sid, host) / ".id_lock"


def remote_pid_path(sid: str, id_: int) -> str:
    """Remote flat naming. Returns a `~`-prefixed path; remote bash will
    expand on use (and SFTP paramiko handles ~ correctly when prepended)."""
    return f"~/.cache/remote-mcp-{sid}-{id_}-pid"


def remote_status_path(sid: str, id_: int) -> str:
    return f"~/.cache/remote-mcp-{sid}-{id_}-status.sh"


def remote_default_log_path(sid: str, id_: int) -> str:
    return f"~/.cache/remote-mcp-{sid}-{id_}.log"
