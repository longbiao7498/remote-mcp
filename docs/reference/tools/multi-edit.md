# MultiEdit

> 中文版本：[multi-edit.zh.md](./multi-edit.zh.md)

Apply a sequence of string replacements to a single remote file in one SFTP read-write cycle, atomically.

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string"},
    "edits": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "old_string": {"type": "string"},
          "new_string": {"type": "string"},
          "replace_all": {"type": "boolean", "default": false}
        },
        "required": ["old_string", "new_string"]
      }
    }
  },
  "required": ["file_path", "edits"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute remote path, or relative to the configured cwd. ~ is NOT supported (use absolute or relative). |
| `edits` | array | yes | — | Ordered list of edit objects to apply |
| `edits[].old_string` | string | yes | — | Exact substring to replace |
| `edits[].new_string` | string | yes | — | Replacement substring |
| `edits[].replace_all` | boolean | no | `false` | If `true`, replace all occurrences of this edit's `old_string` |

## Returns

A string. The format depends on outcome:

**On success:** `Successfully applied <N> edits to <file_path>` where `<N>` is the number of edits in the list.

**On error:** one of the strings listed in [Error wording](#error-wording).

The MCP server appends `\n\n[host=X cwd=Y]` to every output (success and error). The tool's own output is everything before that suffix.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `edits` list is empty | `Error: edits list is empty` |
| File does not exist | `Error: File not found: <file_path>` |
| Edit #N's `old_string` not found (including after prior edits have been applied) | `Error: edit #N: old_string not found` |
| Edit #N's `old_string` found more than once and `replace_all` is `false` | `Error: edit #<N>: old_string found <M> times (lines <L1, L2, ...>). Provide more context or set replace_all=true.` |

## Behavior notes

- **Single SFTP cycle:** the file is read once, all edits are applied in memory in order, then the file is written once. The file is not re-read between edits.
- **Atomicity:** if any edit in the sequence fails (not found, ambiguous match), the entire operation aborts. The file is left unchanged. No partial edits are written.
- **Edit ordering matters:** edits are applied sequentially to the running content. Edit #2 operates on the content produced by edit #1. The `old_string` match for edit #2 is evaluated against the already-modified content, not the original.
- Each edit's `replace_all` flag operates independently. An edit with `replace_all=true` replaces every occurrence of its `old_string` in the content at that point in the sequence.
- Edit indices in error messages are 1-based (`edit #1`, `edit #2`, …).
- The file must be valid UTF-8. Binary files are not supported.
- MultiEdit is not protected against concurrent writers.
- **Network failures are not auto-retried.** v0.2.2: if SSH dies mid-MultiEdit, the agent receives `Error: <ExceptionType>: <message>` and the next tool call triggers reconnect. MultiEdit is NOT auto-retried because read-modify-write semantics make it unsafe — re-execution would see the already-modified file and falsely report `old_string not found`. Agent should `Read` the file first to verify whether the first attempt succeeded.

## Bandwidth/latency profile

- **Transfer size:** the full file is read once and written once regardless of how many edits are in the list. For N edits on the same file, MultiEdit costs the same network transfer as a single [Edit](./edit.md) call.
- **Round-trips:** two SFTP operations on the shared SFTP session; no exec channel.
- **Comparison:** N separate [Edit](./edit.md) calls on the same file cost 2N SFTP transfers. MultiEdit with N edits costs 2.

## See also

- [Edit](./edit.md) — single replacement; same uniqueness semantics for one edit
- [Write](./write.md) — overwrite the entire file
- [Read](./read.md) — read lines from a file
- Spec §5.3.4
