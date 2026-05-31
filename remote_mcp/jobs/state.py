"""State machine + remote observation helpers (spec §7, §8.5)."""
from typing import Iterable


def derive_state(alive: bool, kill_requested: bool) -> str:
    """Derive 4-state per spec §7."""
    if alive and not kill_requested:
        return "running"
    if not alive and not kill_requested:
        return "stopped"
    if not alive and kill_requested:
        return "killed"
    return "kill_failed"  # alive + kill_requested


def build_batched_kill_check(pids: Iterable) -> str:
    """Build the single batched shell command to observe pids + now.

    Output format:
      now=<unix_sec>
      <pid1>=A   (or D)
      <pid2>=A
      ...
    """
    lines = ['echo "now=$(date +%s)"']
    for p in pids:
        lines.append(f'kill -0 {int(p)} 2>/dev/null && echo "{int(p)}=A" || echo "{int(p)}=D"')
    return "; ".join(lines)


def parse_batched_kill_output(out: str) -> tuple:
    """Parse the structured output. Returns (now_unix, {pid: alive_bool})."""
    now = 0
    alive: dict = {}
    for raw_line in out.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("now="):
            try:
                now = int(line[4:].strip())
            except ValueError:
                continue
        elif "=" in line:
            k, v = line.split("=", 1)
            try:
                alive[int(k.strip())] = (v.strip() == "A")
            except ValueError:
                continue
    return now, alive
