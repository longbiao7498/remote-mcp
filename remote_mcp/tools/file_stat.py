"""FileStat tool. See spec §5.3.6."""
import stat as _stat
from datetime import datetime, timezone
from typing import List, Union

from ..connection import SSHConnection
from ..paths import resolve_path


def file_stat(conn: SSHConnection,
              file_paths: Union[str, List[str]]) -> str:
    """
    Query metadata for one or more remote files via SFTP stat.

    Returns type (file/dir/symlink), size, mode (octal), and mtime (ISO 8601)
    for each path. Use this to check existence and metadata without reading
    file content — much faster than Read for a quick size/type check.

    Args:
        conn: established SSHConnection.
        file_paths: a single path (str) or list of paths (List[str]).

    Returns:
        Lines in format: `<path>: exists=<bool> type=<kind> size=<bytes>
            mode=<octal> mtime=<ISO8601>`
        `<path>: exists=false` if the path doesn't exist.
        `<path>: error=permission_denied` if stat fails due to permissions.
        `"Error: file_paths is empty"` if an empty list is passed.
    """
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    if not file_paths:
        return "Error: file_paths is empty"

    sftp = conn.get_sftp()
    lines = []
    for fp in file_paths:
        # Resolve each path individually so a bad entry emits an error line
        # rather than aborting the whole call (consistent with MultiRead).
        try:
            fp = resolve_path(fp, conn.config.cwd or "/")
        except ValueError as e:
            lines.append(f"{fp}: Error: {e}")
            continue

        try:
            st = sftp.stat(fp)
        except IOError:
            lines.append(f"{fp}: exists=false")
            continue
        except PermissionError:
            lines.append(f"{fp}: error=permission_denied")
            continue

        mode = st.st_mode or 0
        if _stat.S_ISDIR(mode):
            kind = "dir"
        elif _stat.S_ISLNK(mode):
            kind = "symlink"
        else:
            kind = "file"
        mtime_iso = (
            datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            .isoformat(timespec="seconds")
        )
        lines.append(
            f"{fp}: exists=true type={kind} size={st.st_size} "
            f"mode={oct(mode)[-4:]} mtime={mtime_iso}"
        )
    return "\n".join(lines)
