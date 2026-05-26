"""Bash tool. See spec §5.3.7."""
from ..connection import SSHConnection


def bash(conn: SSHConnection, command: str,
         run_in_background: bool = False,
         timeout: float = None,
         description: str = "") -> str:
    if timeout is None:
        timeout = float(conn.config.bash_timeout_default)
    if run_in_background:
        return _bash_background(conn, command)
    return _bash_foreground(conn, command, timeout)


def _bash_foreground(conn: SSHConnection, command: str, timeout: float) -> str:
    session = conn.get_bash_session()
    try:
        result = session.execute(command, timeout=timeout)
    except TimeoutError:
        return f"Error: Command timed out after {timeout}s on {conn.config.name}"

    cwd = session.current_cwd()
    # Strip spurious \r characters introduced by PTY line endings
    output = result.output.replace("\r\n", "\n").replace("\r", "")

    prefix = f"[host={conn.config.name} cwd={cwd}]\n"

    if result.exit_code != 0:
        output += f"\n[Exit code: {result.exit_code}]"

    cap = conn.config.bash_output_cap
    if len(output) > cap:
        output = output[:cap] + f"\n... [truncated to {cap} bytes]"

    return prefix + output


def _bash_background(conn: SSHConnection, command: str) -> str:
    # Placeholder; implemented in Task 5.3
    raise NotImplementedError("run_in_background implemented in next task")
