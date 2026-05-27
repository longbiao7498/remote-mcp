# Glob

> 中文版本：[glob.zh.md](./glob.zh.md)

Find files matching a glob pattern on the remote host using server-side `find`.

## Schema

```json
{
  "type": "object",
  "properties": {
    "pattern": {"type": "string"},
    "path":    {"type": "string", "default": "."}
  },
  "required": ["pattern"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `pattern` | string | yes | — | Glob pattern to match against (see pattern-conversion rules below). |
| `path` | string | no | `"."` | Root directory on the remote host where the search starts. |

## Returns

A string. The format depends on outcome:

**On success:** newline-delimited list of matching file paths, sorted (via `sort`). One path per line.

**No matches:**

```
No files found matching pattern
```

**Result capped:**

```
<path1>
<path2>
...
<pathN>
... [truncated to <N> entries]
```

The cap is `conn.config.glob_output_limit` (default `1000`). When the number of matches exceeds the limit, only the first `N` sorted paths are returned followed by the truncation note.

**On error:** one of the strings listed in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `find` exits with a code other than `0` or `1` (e.g., invalid path, permission error) | `Error: <stderr text from find>` |

## Behavior notes

### Pattern-to-`find` conversion

The glob pattern is translated to a `find` expression according to these rules:

| Pattern form | Converted `find` expression | Notes |
|---|---|---|
| `*.ext` | `-name '*.ext'` | No path separators: filename match at any depth |
| `**/*.ext` | `-name '*.ext'` | Leading `**/` with no further `/` in tail: treated as filename-only match |
| `dir/*.ext` | `-wholename '*/dir/*.ext'` | Path segment preserved; leading `*/` added so match is depth-independent |
| `dir/**/*.ext` | `-wholename '*/dir/*/*.ext'` | `**` collapsed to `*`; path segments preserved |

The `find` command always includes `-type f` — directories and symlinks are excluded from results.

### `**` semantics

`**` (globstar) is approximated: it is collapsed to `*` for `find -wholename`. This means `**` matches at any depth but does not span multiple path segments the way shell globstar does. For example, `src/**/*.py` will match `src/a/b.py` but not necessarily `src/a/b/c.py` depending on path depth. This is a documented limitation (spec §9).

### Cap behavior

`find` is piped through `head -<limit+1>`. If more than `limit` lines are returned, the output is truncated to `limit` entries and the truncation note is appended. The cap is applied before returning to the caller.

### stderr suppression

`find` errors (e.g., `Permission denied` on a subdirectory) are redirected to `/dev/null` via `2>/dev/null`. Only structural `find` failures (non-0, non-1 exit codes) are surfaced as errors. Partial results from accessible directories are still returned.

## Bandwidth/latency profile

- The `find` command runs entirely on the remote host. Only the list of matching paths crosses the network.
- One stateless `exec()` channel per call (not the persistent bash session).
- Narrow the `path` argument to a specific subdirectory when searching large directory trees to reduce remote CPU and result size.

## See also

- [Grep](./grep.md) — search file contents rather than filenames
- [Bash](./bash.md) — run arbitrary `find` expressions not expressible via the pattern syntax
- [FileStat](./file-stat.md) — check existence and metadata for known paths
- Spec §5.3.8
