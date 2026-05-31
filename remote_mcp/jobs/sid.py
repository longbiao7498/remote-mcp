"""Derive a stable session ID from the MCP server's parent process.

Spec §12.1. The sid is hash of (PPID, parent process start time, hostname).
Stable across MCP server restarts within the same Claude Code session
(PPID stays the same because Claude Code's PID doesn't change).
"""
import hashlib
import os
import socket
import uuid

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None  # type: ignore


_cached_sid: "tuple[str, str] | None" = None


def derive_sid() -> "tuple[str, str]":
    """Return (sid, source) where sid is 12 hex chars and source is either
    'ppid+starttime' (normal) or 'uuid (psutil fallback: ...)' (degraded).

    Result is cached in module globals — only the first call does work.
    """
    global _cached_sid
    if _cached_sid is not None:
        return _cached_sid

    try:
        if psutil is None:
            raise RuntimeError("psutil not installed")
        ppid = os.getppid()
        parent = psutil.Process(ppid)
        ptime = int(parent.create_time())
        hostname = socket.gethostname()
        raw = f"{ppid}-{ptime}-{hostname}"
        sid = hashlib.sha1(raw.encode()).hexdigest()[:12]
        _cached_sid = (sid, "ppid+starttime")
    except Exception as e:
        sid = uuid.uuid4().hex[:12]
        _cached_sid = (sid, f"uuid (psutil fallback: {e})")

    return _cached_sid


def reset_cache_for_test():
    """Test-only: clear the module-level cache so successive tests can re-derive."""
    global _cached_sid
    _cached_sid = None
