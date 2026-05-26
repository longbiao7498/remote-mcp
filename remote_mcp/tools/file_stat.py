"""FileStat tool. See spec §5.3.6."""
import stat as _stat
from datetime import datetime, timezone
from typing import List, Union

from ..connection import SSHConnection


def file_stat(conn: SSHConnection,
              file_paths: Union[str, List[str]]) -> str:
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    if not file_paths:
        return "Error: file_paths is empty"

    sftp = conn.get_sftp()
    lines = []
    for fp in file_paths:
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
