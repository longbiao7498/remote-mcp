"""RemoteInfo tool — report the connection's configured identity.

CRITICAL: This tool does NOT call SSH. It reads from conn.config and
returns the values we use to *connect* — not whatever the remote thinks
it is. In VPN scenarios, `hostname -I` on the remote returns
internal-network IPs that are not what the client uses to reach it.
For the agent to know "which host am I really operating on?" — the
authoritative answer is the config, not the remote's self-report.
"""


def remote_info(conn) -> str:
    """
    Return a structured summary of the connection's configured identity.

    Args:
        conn: established SSHConnection (only conn.config is accessed).

    Returns:
        5 lines, one per field, in key=value format:
            host=<config-key>
            user=<config-user>
            hostname=<config-hostname>
            port=<config-port>
            jump_host=<config-jump-host or "none">
    """
    c = conn.config
    return (
        f"host={c.name}\n"
        f"user={c.user}\n"
        f"hostname={c.hostname}\n"
        f"port={c.port}\n"
        f"jump_host={c.jump_host or 'none'}\n"
    )
