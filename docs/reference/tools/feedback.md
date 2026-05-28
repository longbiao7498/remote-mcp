# Feedback

> 中文版本：[feedback.zh.md](./feedback.zh.md)

Append a bug report or enhancement idea about the remote-mcp tools themselves to a local JSONL file.

## Schema

```json
{
  "type": "object",
  "properties": {
    "category": {
      "type": "string",
      "enum": ["bug", "enhancement"]
    },
    "summary": {"type": "string"},
    "details": {"type": "string", "default": ""}
  },
  "required": ["category", "summary"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `category` | string | yes | — | Must be exactly `"bug"` or `"enhancement"`. |
| `summary` | string | yes | — | One-line description. Must be non-empty after stripping whitespace. |
| `details` | string | no | `""` | Optional longer description. Stored as-is after stripping; `null` in the JSON entry when empty. |

## Returns

A string. The format depends on outcome:

**On success:**

```
Feedback recorded: [<category>] <summary> -> <feedback_path>
```

`<feedback_path>` is the local filesystem path of the JSONL file, as configured (default `~/.local/share/remote-mcp/feedback.jsonl`).

**On error:** one of the strings listed in [Error wording](#error-wording). Errors do not write to the file.

The MCP server appends `\n\n[host=X cwd=Y]` to every output (success and error).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `category` is not `"bug"` or `"enhancement"` | `Error: category must be 'bug' or 'enhancement', got '<value>'` |
| `summary` is empty or whitespace-only | `Error: summary cannot be empty` |

## Behavior notes

### Scope

Feedback is about the remote-mcp tools themselves — their schemas, error messages, output formats, or missing capabilities. It is not a channel for recording bugs in the user's code or the remote system.

### JSONL entry shape

Each successful call appends exactly one line to the file. The line is a JSON object with these fields:

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `ts` | string | automatic | UTC ISO 8601 with second precision (e.g., `"2026-05-26T10:00:00+00:00"`) |
| `host` | string | automatic | `conn.config.name` — the remote host this MCP server instance is connected to |
| `category` | string | caller | `"bug"` or `"enhancement"` |
| `summary` | string | caller | Stripped value of the `summary` parameter |
| `details` | string or null | caller | Stripped value of `details`, or `null` if `details` was empty |
| `session_pid` | integer | automatic | PID of the local MCP server process |

Example entry (one line in the file):

```json
{"ts": "2026-05-26T10:00:00+00:00", "host": "gpu-box", "category": "bug", "summary": "Glob missed nested matches", "details": "Pattern src/**/*.py returned no results for src/a/b/c.py", "session_pid": 12345}
```

### Local only

The file is written to the local machine only. Nothing is transmitted to a remote host or external service. `conn` is accepted as a parameter solely to read `conn.config.name` for the `host` field.

### Concurrency safety

Multiple per-host MCP server processes may append to the same JSONL file simultaneously. Each call issues a single `write()` of one JSONL line. On POSIX systems, writes of fewer than `PIPE_BUF` bytes (typically 4 KB on Linux) to a file opened with `O_APPEND` are atomic. A single feedback entry is well within this limit. No locking is required.

### File location

The path is taken from config (default `~/.local/share/remote-mcp/feedback.jsonl`). The parent directory is created automatically if it does not exist (`mkdir -p` equivalent). The file is never rotated or truncated automatically.

## Bandwidth/latency profile

- No network activity. All I/O is local filesystem only.
- The call completes in under a millisecond in normal conditions.

## See also

- [Bash](./bash.md) — for operations on the remote system
- Spec §5.3.10
