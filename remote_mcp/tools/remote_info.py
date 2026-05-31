"""RemoteInfo tool — report the connection's configured identity.

CRITICAL: This tool does NOT call SSH. It reads from conn.config and
returns the values we use to *connect* — not whatever the remote thinks
it is. In VPN scenarios, `hostname -I` on the remote returns
internal-network IPs that are not what the client uses to reach it.
For the agent to know "which host am I really operating on?" — the
authoritative answer is the config, not the remote's self-report.
"""
from ..jobs.sid import derive_sid


def remote_info(conn) -> str:
    """
    Return a structured summary of the connection's configured identity.

    Adds `cwd=<value>` (v0.2.0) showing the configured remote working dir.
    Adds `sid=<hex12> (source=<source>)` (v0.3.0) for job panel session ID.
    """
    c = conn.config
    cwd_val = c.cwd if c.cwd else "unknown"
    sid, source = derive_sid()
    return (
        f"host={c.name}\n"
        f"user={c.user}\n"
        f"hostname={c.hostname}\n"
        f"port={c.port}\n"
        f"jump_host={c.jump_host or 'none'}\n"
        f"cwd={cwd_val}\n"
        f"sid: {sid} (source={source})\n"
    )
