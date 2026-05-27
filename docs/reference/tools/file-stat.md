# FileStat

> 中文版本：[file-stat.zh.md](./file-stat.zh.md)

Get metadata (existence, size, mtime, mode) for one or more remote paths without transferring file content.

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_paths": {
      "oneOf": [
        {"type": "string"},
        {"type": "array", "items": {"type": "string"}}
      ]
    }
  },
  "required": ["file_paths"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_paths` | string or array of strings | yes | — | Single path or list of paths on the remote host to stat |

## Returns

A string. The format depends on outcome:

**On success:** one line per path, in the same order as the input:

```
<path>: exists=true type=<kind> size=<bytes> mode=<octal4> mtime=<iso8601>
```

- `kind` is one of `file`, `dir`, or `symlink`.
- `mode` is the last four octal digits of the raw mode bits (e.g., `0644`).
- `mtime` is UTC ISO 8601 with second precision (e.g., `2026-05-26T10:00:00+00:00`).

**Path does not exist:**

```
<path>: exists=false
```

**Permission error:**

```
<path>: error=permission_denied
```

**On error:** one of the strings listed in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `file_paths` is an empty list | `Error: file_paths is empty` |

Individual per-path errors (non-existence, permission denied) appear inline in the output, not as top-level error returns — see Returns above.

## Behavior notes

- Accepts a bare string or a JSON array. A single string is normalized to a one-element list internally.
- Uses SFTP `stat()` on the already-open SFTP client — no new SSH channel is opened per call.
- Results are returned in the same order as the input `file_paths`.
- `symlink` is detected via `S_ISLNK()` on the raw mode bits. SFTP `stat()` follows symlinks by default; the reported type reflects the link target, not the link itself, unless the stat call is against a dangling symlink (which reports as `exists=false`).
- The `mode` field contains the final four octal digits only (e.g., `0755`, not `0o100755`).
- `mtime` is timezone-aware UTC; the `+00:00` suffix is always present.
- The tool does not raise exceptions. All per-path failures are folded into the returned string.

## Bandwidth/latency profile

- Each path stat is one SFTP message on the reused SFTP channel — typically < 100 bytes exchanged per path.
- Batching multiple paths in a single call avoids multiple round-trips compared to iterating with [Bash](./bash.md) `stat`.
- No file content is transferred regardless of file size. Use FileStat to probe large files before deciding whether to call [Read](./read.md).

## See also

- [Read](./read.md) — read file content after confirming size with FileStat
- [Bash](./bash.md) — for metadata not exposed by FileStat (e.g., symlink target, extended attributes)
- Spec §5.3.6
