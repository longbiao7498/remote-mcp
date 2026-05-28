# MultiRead

> 中文版本：[multi-read.zh.md](./multi-read.zh.md)

Read multiple remote files in a single SSH round-trip using a composed server-side shell script.

## Schema

```json
{
  "type": "object",
  "properties": {
    "reads": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "file_path": {"type": "string"},
          "offset": {"type": "integer", "default": 1},
          "limit": {"type": "integer", "default": 2000}
        },
        "required": ["file_path"]
      }
    }
  },
  "required": ["reads"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `reads` | array | yes | — | Ordered list of file-read descriptors |
| `reads[].file_path` | string | yes | — | Absolute remote path, or relative to the configured cwd. ~ is NOT supported (use absolute or relative). |
| `reads[].offset` | integer | no | `1` | First line to return (1-based) |
| `reads[].limit` | integer | no | `2000` | Maximum number of lines to return for this file |

## Returns

A string. The format depends on outcome:

**On success:** A concatenated string of per-file sections separated by header lines. Each file section has the form:

```
===FILE: <file_path>===
     <lineno>\t<line>
     <lineno>\t<line>
     ...

```

Files that do not exist are represented as:

```
===FILE: <file_path>===
NOT_FOUND

```

Line numbers within each section are 1-based and start from the `offset` value for that read entry. The overall output is capped at `read_size_cap` bytes (default 256 KB); if the cap is reached, output is truncated at that byte boundary and `\n... [truncated to <N> bytes]` is appended.

**On error:** one of the strings listed in [Error wording](#error-wording).

The MCP server appends `\n\n[host=X cwd=Y]` to every output (success and error). The tool's own output is everything before that suffix.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `reads` list is empty | `Error: reads list is empty` |
| The remote exec command fails and produces no stdout | `Error: <stderr text>` or `Error: multi_read failed` |

## Behavior notes

- A single shell script is constructed client-side and sent to the remote host via one `conn.exec()` call. The script emits internal `===RMCP_FILE_BEGIN:...===` and `===RMCP_FILE_END:...:(OK|NOT_FOUND)===` markers that the client then parses; these markers do not appear in the returned output.
- Server-side slicing: each file uses `sed -n '<offset>,<end>p; <end+1>q'`. Only the requested lines cross the network, not the full files.
- File existence is tested with `[ -f <file_path> ]` in the shell script. A path that exists but is a directory will be reported as `NOT_FOUND`.
- The size cap is applied to the final formatted output across all files, not per file. Files appearing earlier in the list are more likely to be included in full when the cap is reached.
- The `conn.exec()` call uses a 60-second timeout for the composite script. Requests involving very large files or many files may be slow.
- Line-number formatting matches [Read](./read.md): five spaces, the line number (starting at `offset`), a tab, then the raw line content.
- The internal markers (`===RMCP_FILE_BEGIN:...===`, `===RMCP_FILE_END:...===`) are not guaranteed to be absent from file content; files that happen to contain those exact strings could cause parse artifacts. This is an edge case for files that contain the literal string `===RMCP_FILE_BEGIN:` at the start of a line.

## Bandwidth/latency profile

- **Round-trips:** one SSH exec channel for any number of files.
- **Transfer size:** proportional to the sum of requested line ranges across all files, subject to SSH compression.
- **Comparison:** N separate [Read](./read.md) calls each consume one round-trip; MultiRead with N entries consumes one. On a 500 ms RTT link, five files read separately take at least 2.5 seconds of pure latency; MultiRead takes at most ~0.5 seconds.

## See also

- [Read](./read.md) — read lines from a single file
- [FileStat](./file-stat.md) — check existence and size of multiple files without transferring content
- [Grep](./grep.md) — search across multiple files server-side
- Spec §5.3.5
