# Read

> 中文版本：[read.zh.md](./read.zh.md)

Read lines from a file on the remote host using server-side `sed` slicing.

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string",
      "description": "Absolute path to the file on the remote server"
    },
    "offset": {
      "type": "integer",
      "description": "Start line number (1-based). Default: 1",
      "default": 1
    },
    "limit": {
      "type": "integer",
      "description": "Max lines to read. Default: 2000",
      "default": 2000
    }
  },
  "required": ["file_path"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_path` | string | yes | — | Absolute path to the file on the remote host |
| `offset` | integer | no | `1` | First line to return (1-based). Must be >= 1. |
| `limit` | integer | no | `2000` | Maximum number of lines to return. Must be >= 1. |

## Returns

A string. The format depends on outcome:

**On success:** Each line is prefixed with a 1-based line number in the format `     <lineno>\t<content>` (five spaces, the line number, a tab character, then the raw line content including its newline). Lines are numbered starting from `offset`. If the formatted output exceeds `read_size_cap` (default 256 KB), the output is truncated at that byte boundary and a note is appended: `\n... [truncated to <N> bytes]`.

**On error:** one of the strings listed in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `offset` parameter is less than 1 | `Error: offset must be >= 1, got <offset>` |
| `limit` parameter is less than 1 | `Error: limit must be >= 1, got <limit>` |
| File does not exist on remote host | `Error: File not found: <file_path>` |
| Any other `sed` / SSH execution error | `Error: <stderr text>` or `Error: unknown error reading file` |

## Behavior notes

- Uses `sed -n '<offset>,<end>p; <end+1>q'` server-side. Only the requested lines cross the network. Reading 20 lines from a 100 MB file transfers only those 20 lines.
- The remote command runs via `conn.exec()` — a stateless one-shot SSH channel, not the persistent bash session.
- `stderr` from the remote `sed` invocation is merged into the error string. The tool does not raise exceptions.
- If the file has fewer lines than requested, only the available lines are returned; no error is produced.
- The size cap is applied after line-number formatting. A file whose formatted output exceeds 256 KB is truncated mid-output; the last partial line may be cut.
- To check whether a file exists or obtain its size without transferring content, use [FileStat](./file-stat.md).

## Bandwidth/latency profile

- **Transfer size:** proportional to the lines requested, not the file size. A 2000-line read of a typical source file transfers 50–150 KB.
- **Round-trips:** one SSH exec channel per call.
- **Compression:** SSH-level compression is enabled by default; text content typically compresses 3–10×.
- **Alternative:** [MultiRead](./multi-read.md) batches multiple file reads into a single round-trip.

## See also

- [MultiRead](./multi-read.md) — batch-read multiple files in one round-trip
- [FileStat](./file-stat.md) — existence and size check without content transfer
- [Grep](./grep.md) — search for specific text, returning only matching lines
- Spec §5.3.1
