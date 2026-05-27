"""Read tool. See spec §5.3.1."""
import shlex

from ..connection import SSHConnection


def read(conn: SSHConnection, file_path: str,
         offset: int = 1, limit: int = 2000) -> str:
    """
    Read lines from a remote file with server-side slicing.

    Uses `sed -n '<start>,<end>p; <end+1>q'` so only the requested lines
    cross the network — reading 20 lines from a 100 MB file transfers
    only those 20 lines, not the whole file.

    Output format matches Claude Code's native Read:
    `     <lineno>\\t<line>` (5 spaces + 1-based line number + tab + content).

    Args:
        conn: established SSHConnection.
        file_path: absolute path on the remote host.
        offset: 1-based start line. Default 1.
        limit: max lines to read. Default 2000.

    Returns:
        Formatted lines on success. Capped at `conn.config.read_size_cap`
        bytes (default 256 KB) with a truncation note when exceeded.
        `"Error: File not found: <path>"` if the file doesn't exist.
        `"Error: <stderr>"` for other read errors.

    Note: To just check existence/size of a file, use FileStat — it returns
    a few bytes vs potentially MB of file content.
    """
    if offset < 1:
        return f"Error: offset must be >= 1, got {offset}"
    if limit < 1:
        return f"Error: limit must be >= 1, got {limit}"

    end = offset + limit - 1
    # sed -n '<start>,<end>p; <end+1>q' file
    cmd = (
        f"sed -n '{offset},{end}p; {end+1}q' "
        f"{shlex.quote(file_path)}"
    )
    result = conn.exec(cmd)

    if result.exit_code != 0:
        stderr = result.stderr or ""
        if "No such file" in stderr or "cannot open" in stderr:
            return f"Error: File not found: {file_path}"
        return f"Error: {stderr.strip() or 'unknown error reading file'}"

    lines = result.stdout.splitlines(keepends=True)
    parts = []
    for i, line in enumerate(lines):
        parts.append(f"     {offset + i}\t{line}")
    out = "".join(parts)

    cap = conn.config.read_size_cap
    if len(out) > cap:
        out = out[:cap] + f"\n... [truncated to {cap} bytes]"
    return out
