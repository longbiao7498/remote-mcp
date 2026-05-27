"""Grep tool. See spec §5.3.9."""
import shlex

from ..connection import SSHConnection


_VALID_OUTPUT_MODES = ("content", "files_with_matches", "count")


def grep_tool(conn: SSHConnection, pattern: str, path: str,
              include: str = "",
              case_insensitive: bool = False,
              before: int = 0,
              after: int = 0,
              context: int = 0,
              head_limit: int = 200,
              output_mode: str = "content") -> str:
    """
    Search for a pattern recursively in files on the remote host.

    Runs `grep -rn -E <pattern> <path>` with optional context lines and
    file filtering. Three output modes: "content" (lines with matches),
    "files_with_matches" (just filenames), "count" (match count per file).

    Args:
        conn: established SSHConnection.
        pattern: extended regex pattern to search for.
        path: starting directory or file for the search.
        include: optional glob pattern for filename filtering (e.g., "*.py").
        case_insensitive: if True, use grep -i.
        before: number of lines before the match. Ignored if context > 0.
        after: number of lines after the match. Ignored if context > 0.
        context: if > 0, show this many lines before and after (overrides
            before/after).
        head_limit: max lines to return. Default 200.
        output_mode: "content" (default), "files_with_matches", or "count".

    Returns:
        Formatted grep output (varies by output_mode).
        `"No matches found"` if exit code is 1 (no match) or output is empty.
        `"Error: <stderr>"` if exit code is 2 (grep error, e.g., invalid regex).
        Output is truncated to head_limit lines.
    """
    if output_mode not in _VALID_OUTPUT_MODES:
        return (
            f"Error: invalid output_mode: {output_mode!r}. "
            f"Must be one of {_VALID_OUTPUT_MODES}."
        )

    if output_mode == "content":
        mode_flag = "-n"
    elif output_mode == "files_with_matches":
        mode_flag = "-l"
    else:
        mode_flag = "-c"

    flags = ["-r", mode_flag]
    if case_insensitive:
        flags.append("-i")

    if output_mode == "content":
        if context > 0:
            flags.append(f"-C{context}")
        else:
            if before > 0:
                flags.append(f"-B{before}")
            if after > 0:
                flags.append(f"-A{after}")

    include_opt = f"--include={shlex.quote(include)}" if include else ""

    cmd = (
        f"grep {' '.join(flags)} {include_opt} -E "
        f"{shlex.quote(pattern)} {shlex.quote(path)} "
        f"| head -{head_limit}"
    )
    result = conn.exec(cmd)
    if result.exit_code == 2:
        return f"Error: {result.stderr.strip()}"
    if result.exit_code == 1 or not result.stdout.strip():
        return "No matches found"
    return result.stdout
