# Write

> 中文版本：[write.zh.md](./write.zh.md)

Write text content to a file on the remote host via SFTP, creating parent directories as needed.

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string"},
    "content": {"type": "string"}
  },
  "required": ["file_path", "content"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute path to the file on the remote host |
| `content` | string | yes | — | Text content to write (UTF-8 encoded) |

## Returns

A string. The format depends on outcome:

**On success:** `Successfully wrote <N> characters to <file_path>` where `<N>` is `len(content)` (Unicode character count, not byte count).

**On error:** one of the strings listed in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| User lacks write permission on `<file_path>` or its parent directory (SFTP `PermissionError`, or `IOError` with `errno=EACCES`) | `Error: Permission denied: <file_path>` |
| Other SFTP write failure (target is a directory, disk full, invalid path, etc.) | `Error: <message>` — the underlying exception's `str()`, or the exception class name if the message is empty |

## Behavior notes

- The file is written via SFTP binary transfer. The entire `content` string is UTF-8 encoded and sent as a single SFTP write. The operation is binary-safe at the transport level, but `content` must be valid UTF-8 text; binary data is not supported.
- If the file already exists, it is overwritten without warning. There is no append mode.
- Parent directories are created recursively using SFTP-only operations (`sftp.stat` + `sftp.mkdir`), with no shell channel opened. Each directory level is stat-checked before a mkdir attempt; a concurrent creation race is silently ignored.
- The character count `<N>` in the success string is `len(content)` in Python — the number of Unicode code points, which may differ from the byte length for non-ASCII content.
- Write is not atomic: a failure after `sftp.file(file_path, "w")` is opened but before the write completes may leave the file truncated.

## Bandwidth/latency profile

- **Transfer size:** equal to the UTF-8 byte length of `content`, subject to SSH compression.
- **Round-trips:** one SFTP session reused from the connection; no additional SSH exec channel.
- **mkdir overhead:** one SFTP `stat` + one `mkdir` per directory level in the path that does not yet exist.
- Compose the complete file content before calling Write rather than calling Write incrementally — each call is an independent full overwrite.

## See also

- [Edit](./edit.md) — replace a substring in an existing file without transferring the full file twice
- [MultiEdit](./multi-edit.md) — apply multiple replacements to one file in a single SFTP round-trip
- Spec §5.3.2
