"""Panel startup initialization (spec §4.1).

Called once at server.main() after sid derivation. Creates the
local directory tree and an empty next_id file. Fail-fast on errors.
"""
from .paths import (
    local_sid_host_dir, local_archive_dir, local_zombie_dir,
    local_next_id_path, local_id_lock_path,
)


def init_panel(sid: str, host: str) -> None:
    """Create local panel directory tree for this sid+host.

    Idempotent. Raises OSError (or subclass) if any mkdir / write fails;
    caller (server.main) should let that propagate to terminate the MCP
    process with a clear error.
    """
    sid_host = local_sid_host_dir(sid, host)
    archive = local_archive_dir(sid, host)
    zombie = local_zombie_dir(sid, host)

    sid_host.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    zombie.mkdir(parents=True, exist_ok=True)

    next_id = local_next_id_path(sid, host)
    if not next_id.exists():
        next_id.write_text("0")

    id_lock = local_id_lock_path(sid, host)
    if not id_lock.exists():
        id_lock.touch()
