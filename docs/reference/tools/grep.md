# Grep

> 中文版本：[grep.zh.md](./grep.zh.md)

Search file contents for an extended regex pattern on the remote host using server-side `grep`.

## Schema

```json
{
  "type": "object",
  "properties": {
    "pattern":          {"type": "string"},
    "path":             {"type": "string"},
    "include":          {"type": "string", "default": ""},
    "case_insensitive": {"type": "boolean", "default": false},
    "before":           {"type": "integer", "default": 0},
    "after":            {"type": "integer", "default": 0},
    "context":          {"type": "integer", "default": 0},
    "head_limit":       {"type": "integer", "default": 200},
    "output_mode": {
      "type": "string",
      "enum": ["content", "files_with_matches", "count"],
      "default": "content"
    }
  },
  "required": ["pattern", "path"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `pattern` | string | yes | — | Extended regex pattern (`grep -E`). |
| `path` | string | yes | — | Starting file or directory on the remote host. Searched recursively when a directory. |
| `include` | string | no | `""` | Filename glob passed to `--include` (e.g., `"*.py"`). Empty string means no filtering. |
| `case_insensitive` | boolean | no | `false` | When `true`, passes `-i` to `grep`. |
| `before` | integer | no | `0` | Lines of context before each match (`-B N`). Ignored when `context > 0` or `output_mode` is not `"content"`. |
| `after` | integer | no | `0` | Lines of context after each match (`-A N`). Ignored when `context > 0` or `output_mode` is not `"content"`. |
| `context` | integer | no | `0` | Lines of context before and after each match (`-C N`). When `> 0`, overrides `before` and `after`. Applies only in `output_mode="content"`. |
| `head_limit` | integer | no | `200` | Maximum lines of output returned. Applied via `| head -<N>` server-side. |
| `output_mode` | string | no | `"content"` | Controls what `grep` outputs. See output mode table below. |

### Output modes

| `output_mode` value | `grep` flag | Output format |
|---|---|---|
| `"content"` (default) | `-n` | `<path>:<lineno>:<matched line>`, one match per line. Context lines use `-` as separator when `before`/`after`/`context` is set. |
| `"files_with_matches"` | `-l` | One file path per line. Context parameters are ignored. |
| `"count"` | `-c` | `<path>:<count>` per file. Context parameters are ignored. |

## Returns

A string. The format depends on outcome:

**On success:** raw `grep` output as described by `output_mode`, truncated to `head_limit` lines.

**No matches (exit code 1 or empty output):**

```
No matches found
```

**On error:** one of the strings listed in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `grep` exits with code `2` (e.g., invalid regex, unreadable path) | `Error: <stderr text from grep>` |
| `output_mode` is not one of the three valid values | `Error: invalid output_mode: '<value>'. Must be one of ('content', 'files_with_matches', 'count').` |

## Behavior notes

- Runs `grep -r -I -E` (recursive, **binary-files skipped**, extended regex). The `-r` and `-I` flags are always present. The `-I` flag means binary files (ELF executables, vim swap files, archives, etc.) are silently excluded — matches inside binary content are almost never meaningful to an agent and previously polluted output. This matches native ripgrep behavior. There is no opt-in flag to search binary files; if you genuinely need that, use Bash with explicit `grep` flags.
- Context parameters (`before`, `after`, `context`) are passed only when `output_mode="content"`. In `"files_with_matches"` and `"count"` modes these parameters are silently ignored — the underlying `grep` flags would conflict with `-l` and `-c`.
- When both `context > 0` and one or both of `before`/`after` are set, `context` takes precedence and overrides both.
- `include` is passed as `--include=<value>`. The value is shell-quoted before insertion into the command. An empty string omits the flag entirely.
- The `head_limit` cap is applied by `| head -<N>` on the remote side, before output is transferred. It limits the total output lines, not just matching lines — context lines and `grep` separator lines (`--`) count toward the limit.
- `multiline` pattern matching is not supported. The implementation uses POSIX `grep`, which matches per line only. This is a documented limitation (spec §5.3.9).
- Exit code `1` (no match) and empty stdout are both mapped to `"No matches found"`. Exit code `0` with non-empty output is passed through as-is.
- Runs via `conn.exec()` — a stateless one-shot SSH channel, not the persistent bash session.

## Bandwidth/latency profile

- Only matching lines (plus requested context) cross the network. `head_limit` provides a hard cap on the transferred line count.
- One stateless `exec()` channel per call.
- Using `output_mode="files_with_matches"` or `"count"` transfers significantly less data when the number of matching files is small relative to match count.
- Context lines (`-A/-B/-C`) eliminate a follow-up [Read](./read.md) call when surrounding lines are needed.

## See also

- [Read](./read.md) — retrieve full file content when grep context is insufficient
- [Glob](./glob.md) — find files by name rather than content
- [Bash](./bash.md) — run arbitrary `grep` invocations not expressible via this schema
- Spec §5.3.9
