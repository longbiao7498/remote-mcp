"""Glob tool. See spec §5.3.8."""
import shlex

from ..connection import SSHConnection


def _glob_to_find_expr(pattern: str) -> str:
    """
    Convert a glob pattern into a `find` expression.

    Rules:
      "*.ext"           → -name '*.ext'              (filename only, any depth)
      "**/*.ext"        → -name '*.ext'              (recursive filename)
      "dir/*.ext"       → -wholename '*/dir/*.ext'   (path segment + filename)
      "dir/**/*.ext"    → -wholename '*/dir/*/*.ext' (path segments + recursive)

    Find's -wholename matches the full path against the shell glob.
    A leading "*/" makes the path-segment patterns match at any depth.

    The '**' (globstar) is collapsed to '*' for find's purposes; this is the
    documented approximation. Spec §14 lists this as a known limitation.
    """
    if "/" not in pattern:
        # Pure filename pattern
        return f"-name '{pattern}'"
    # Special case: "**/<filename_pattern>" — treat as just the filename pattern
    if pattern.startswith("**/") and "/" not in pattern[3:]:
        return f"-name '{pattern[3:]}'"
    # First, normalize ** to * (find's -wholename doesn't honor globstar)
    normalized = pattern.replace("**", "*")
    # Strip leading "*/" if pattern already starts with one to avoid "**"
    # Then prepend "*/" so the pattern matches at any depth
    if not normalized.startswith("*/"):
        normalized = "*/" + normalized
    return f"-wholename '{normalized}'"


def glob_tool(conn: SSHConnection, pattern: str, path: str = ".") -> str:
    find_expr = _glob_to_find_expr(pattern)
    limit = conn.config.glob_output_limit
    # Use bash -c so the quoting in find_expr is preserved
    cmd = (
        f"find {shlex.quote(path)} "
        f"\\( {find_expr} \\) -type f 2>/dev/null "
        f"| sort | head -{limit + 1}"   # +1 to detect truncation
    )
    result = conn.exec(cmd)
    if result.exit_code not in (0, 1):
        return f"Error: {result.stderr.strip()}"

    lines = result.stdout.splitlines()
    if not lines:
        return "No files found matching pattern"

    if len(lines) > limit:
        truncated = "\n".join(lines[:limit])
        return truncated + f"\n... [truncated to {limit} entries]"
    return result.stdout
