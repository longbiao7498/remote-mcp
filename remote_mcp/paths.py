"""Path resolution. See spec §6.3.

resolve_path() maps a tool-provided path (absolute / relative / "." / "..")
to a remote absolute path, anchored at the configured cwd for relative paths.
Empty paths and ~-prefixed paths raise ValueError — tools convert these to
their `Error: ...` return strings.
"""
import posixpath


def resolve_path(path: str, cwd: str) -> str:
    """
    Resolve a tool's path argument to a remote absolute path.

    Args:
        path: the user-supplied path. May be absolute (`/...`), relative
            (`foo`, `./foo`, `../foo`), or `.`.
        cwd: the configured remote cwd (absolute path).

    Returns:
        Absolute remote path with `.` and `..` collapsed.

    Raises:
        ValueError: if path is empty or starts with `~` (tilde-expansion at
            the tool layer is not supported — pass absolute or relative-to-cwd).
    """
    if not path:
        raise ValueError("empty path")
    if path.startswith("~"):
        raise ValueError(
            "path starts with '~' — use an absolute path, "
            "or a path relative to the configured cwd"
        )
    if path.startswith("/"):
        return path
    return posixpath.normpath(posixpath.join(cwd, path))
