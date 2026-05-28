"""MultiRead tool. See spec §5.3.5."""
import re
import shlex
from typing import List, Dict

from ..connection import SSHConnection
from ..paths import resolve_path


_MARKER_BEGIN_RE = re.compile(r"^===RMCP_FILE_BEGIN:(.+)===$")
_MARKER_END_RE = re.compile(r"^===RMCP_FILE_END:(.+):(OK|NOT_FOUND)===$")


def multi_read(conn: SSHConnection, reads: List[Dict]) -> str:
    """
    Read multiple files in a single round-trip via a composed shell script.

    More efficient than calling Read multiple times when fetching many small
    files (e.g., config files across a directory tree). Each read dict specifies
    file_path, offset (default 1), and limit (default 2000). Output is
    pre-formatted with line numbers per file.

    Args:
        conn: established SSHConnection.
        reads: list of read dicts. Each has 'file_path', and optional
            'offset' (1-based, default 1) and 'limit' (max lines, default 2000).

    Returns:
        Formatted multi-file output with `===FILE: <path>===` headers separating
        sections. Each file section shows `     <lineno>\\t<line>` format.
        NOT_FOUND files are marked `===FILE: <path>===\\nNOT_FOUND\\n\\n`.
        Output is capped at `conn.config.read_size_cap` bytes (default 256 KB)
        with truncation note when exceeded.
        `"Error: reads list is empty"` if reads is [].
        `"Error: ..."` on command execution failures (rare).
    """
    if not reads:
        return "Error: reads list is empty"

    # Resolve relative paths against configured cwd. Work with a shallow copy
    # of each dict so the caller's list is not mutated.
    resolved_reads = []
    for r in reads:
        r = dict(r)
        raw_fp = r.get("file_path", "")
        try:
            r["file_path"] = resolve_path(raw_fp, conn.config.cwd or "/")
        except ValueError as e:
            # Store the error string in the dict; the shell script will not
            # be generated for this entry — we emit an error chunk instead.
            r["_path_error"] = str(e)
        resolved_reads.append(r)

    # Build shell script: for each read, emit BEGIN marker, then sed, then END marker
    script_parts = []
    for r in resolved_reads:
        if "_path_error" in r:
            continue  # Will be handled in output assembly below
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

    # Entries without path errors that need a shell round-trip
    shell_reads = [r for r in resolved_reads if "_path_error" not in r]

    raw_output = ""
    if script_parts:
        cmd = "; ".join(script_parts)
        result = conn.exec(cmd, timeout=60.0)
        if result.exit_code != 0 and not result.stdout:
            return f"Error: {result.stderr.strip() or 'multi_read failed'}"
        raw_output = result.stdout

    # Parse shell output into per-file chunks
    shell_chunks = _format_multi_read_output(raw_output, shell_reads, conn.config.read_size_cap)

    # Weave error chunks back in the original order
    if not any("_path_error" in r for r in resolved_reads):
        # Fast path: no resolution errors — return shell output directly
        return shell_chunks

    # Assemble in original order
    shell_chunk_map = _parse_file_chunks(shell_chunks)
    out_parts = []
    for r in resolved_reads:
        if "_path_error" in r:
            out_parts.append(f"===FILE: {r.get('file_path', '')}===\nError: {r['_path_error']}\n\n")
        else:
            fp = r["file_path"]
            out_parts.append(shell_chunk_map.get(fp, f"===FILE: {fp}===\nNOT_FOUND\n\n"))
    out = "".join(out_parts)
    if len(out) > conn.config.read_size_cap:
        out = out[:conn.config.read_size_cap] + f"\n... [truncated to {conn.config.read_size_cap} bytes]"
    return out


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


def _parse_file_chunks(formatted: str) -> Dict[str, str]:
    """
    Parse a formatted multi-read output string into a dict mapping
    file_path → its full chunk text (including the `===FILE: <path>===` header).

    Used when weaving error chunks back in original order for mixed
    (some resolved, some path-error) multi_read calls.
    """
    chunks: Dict[str, str] = {}
    _CHUNK_HEADER_RE = re.compile(r"^===FILE: (.+)===$", re.MULTILINE)
    positions = [(m.start(), m.group(1)) for m in _CHUNK_HEADER_RE.finditer(formatted)]
    for idx, (start, fp) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(formatted)
        chunks[fp] = formatted[start:end]
    return chunks
