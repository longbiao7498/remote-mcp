# Edit

> 中文版本：[edit.zh.md](./edit.zh.md)

Replace an exact substring in a remote file via SFTP read-modify-write, with a uniqueness check by default.

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string"},
    "old_string": {"type": "string"},
    "new_string": {"type": "string"},
    "replace_all": {"type": "boolean", "default": false}
  },
  "required": ["file_path", "old_string", "new_string"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute path to the file on the remote host |
| `old_string` | string | yes | — | The exact substring to replace |
| `new_string` | string | yes | — | The replacement substring |
| `replace_all` | boolean | no | `false` | If `true`, replace all occurrences; skip uniqueness check |

## Returns

A string. The format depends on outcome:

**On success:** `Successfully edited <file_path>`

**On error:** one of the strings listed in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| File does not exist | `Error: File not found: <file_path>` |
| `old_string` not present in file | `Error: old_string not found in <file_path>` |
| `old_string` present more than once and `replace_all` is `false` | `Error: old_string found <N> times in <file_path>. Provide more context to match uniquely, or set replace_all=true to replace all.` |

## Behavior notes

- The file is read in full via SFTP, modified in memory, then written back in full via SFTP. Both the read and the write transfer the complete file content over the network.
- **Uniqueness check (default behavior, `replace_all=false`):** `old_string` must appear exactly once in the file. Zero matches and more-than-one matches both produce errors and leave the file unchanged.
- **`replace_all=true`:** all occurrences are replaced in a single `str.replace()` call. The zero-match case still returns an error.
- On any error (file not found, zero matches, ambiguous match), **the file is not written**. No partial state is possible from an error path.
- Edit is not protected against concurrent writers. Only one agent operating on a file at a time is safe.
- For multiple replacements in the same file, [MultiEdit](./multi-edit.md) reads and writes the file once rather than once per replacement.
- The file must be valid UTF-8. Binary files are not supported.

## Bandwidth/latency profile

- **Transfer size:** the full file is read once and written once per Edit call. For a 50 KB source file, each Edit transfers ~100 KB total (read + write), subject to SSH compression.
- **Round-trips:** two SFTP operations (read + write) on the shared SFTP session; no additional exec channel.
- **Alternative:** [MultiEdit](./multi-edit.md) collapses N edits on the same file to one read + one write.

## See also

- [MultiEdit](./multi-edit.md) — apply multiple edits to one file atomically
- [Write](./write.md) — overwrite the entire file
- [Read](./read.md) — read lines from a file
- Spec §5.3.3
