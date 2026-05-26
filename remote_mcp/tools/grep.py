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
