"""MultiRead tool. See spec §5.3.5."""
import re
import shlex
from typing import List, Dict

from ..connection import SSHConnection


_MARKER_BEGIN_RE = re.compile(r"^===RMCP_FILE_BEGIN:(.+)===$")
_MARKER_END_RE = re.compile(r"^===RMCP_FILE_END:(.+):(OK|NOT_FOUND)===$")


def multi_read(conn: SSHConnection, reads: List[Dict]) -> str:
    if not reads:
        return "Error: reads list is empty"

    # Build shell script: for each read, emit BEGIN marker, then sed, then END marker
    script_parts = []
    for r in reads:
        fp = r["file_path"]
        offset = r.get("offset", 1)
        limit = r.get("limit", 2000)
        end = offset + limit - 1
        qfp = shlex.quote(fp)
        script_parts.append(
            f'echo "===RMCP_FILE_BEGIN:{fp}==="; '
            f'if [ -f {qfp} ]; then '
            f"  sed -n '{offset},{end}p; {end+1}q' {qfp}; "
            f'  echo "===RMCP_FILE_END:{fp}:OK==="; '
            f'else '
            f'  echo "===RMCP_FILE_END:{fp}:NOT_FOUND==="; '
            f'fi'
        )
    cmd = "; ".join(script_parts)
    result = conn.exec(cmd, timeout=60.0)
    if result.exit_code != 0 and not result.stdout:
        return f"Error: {result.stderr.strip() or 'multi_read failed'}"

    # Parse the output into per-file chunks
    return _format_multi_read_output(result.stdout, reads, conn.config.read_size_cap)


def _format_multi_read_output(raw: str, reads: List[Dict], cap: int) -> str:
    """Split raw output by BEGIN/END markers; add line-number prefixes per file."""
    out_chunks = []
    lines = raw.splitlines(keepends=True)
    i = 0
    read_index = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        m_begin = _MARKER_BEGIN_RE.match(line)
        if m_begin:
            file_path = m_begin.group(1)
            offset = reads[read_index].get("offset", 1)
            # Collect content lines until END marker
            content_lines = []
            i += 1
            while i < len(lines):
                inner = lines[i]
                m_end = _MARKER_END_RE.match(inner.rstrip("\n"))
                if m_end:
                    status = m_end.group(2)
                    if status == "NOT_FOUND":
                        out_chunks.append(f"===FILE: {file_path}===\nNOT_FOUND\n\n")
                    else:
                        header = f"===FILE: {file_path}===\n"
                        body = "".join(
                            f"     {offset + j}\t{l}"
                            for j, l in enumerate(content_lines)
                        )
                        out_chunks.append(header + body + "\n")
                    i += 1
                    read_index += 1
                    break
                content_lines.append(inner)
                i += 1
        else:
            i += 1

    out = "".join(out_chunks)
    if len(out) > cap:
        out = out[:cap] + f"\n... [truncated to {cap} bytes]"
    return out
