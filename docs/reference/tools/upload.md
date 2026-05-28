# Upload

> 中文版本：[upload.zh.md](./upload.zh.md)

Push a local file to the remote host via SFTP. Binary-safe.

**On Linux/macOS, prefer `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** — non-blocking, any size, resumable with `rsync`. Upload is primarily for Windows users without `scp` in PATH.

## Schema

```json
{
  "type": "object",
  "properties": {
    "local_path": {"type": "string"},
    "remote_path": {"type": "string"}
  },
  "required": ["local_path", "remote_path"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `local_path` | string | yes | — | Absolute LOCAL path or with ~ (expanded via `os.path.expanduser`). NOT subject to the configured remote cwd. |
| `remote_path` | string | yes | — | Absolute remote path, or relative to the configured cwd (same as Read/Write/etc.). Overwrites if exists. Parent directories are auto-created via SFTP `mkdir`. |

## Returns

A string.

**On success:** `Successfully uploaded <N> bytes from <local_path> to <remote_path>` where `<N>` is the byte length of the local file.

**On error:** one of the strings in [Error wording](#error-wording).

The MCP server appends `\n\n[host=X cwd=Y]` to every output (success and error). The tool's own output is everything before that suffix.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `local_path` does not exist | `Error: Local file not found: <local_path>` |
| `local_path` is a directory | `Error: Local path is a directory, not a file: <local_path>` |
| Local file size > `conn.config.transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Remote write denied (`PermissionError` or `IOError` with `errno=EACCES`) | `Error: Permission denied: <remote_path>` |
| Other SFTP failure | `Error: <message>` |

## Behavior notes

- Uses paramiko's `sftp.put(local, remote)` which streams the file — no full file load into memory. Suitable for files up to `transfer_size_cap`.
- Parent directory of `remote_path` is created recursively via SFTP `mkdir` (same mechanism as Write).
- The local file is read in binary mode; UTF-8 text encoding is NOT assumed.
- The transfer blocks until completion — there is no progress reporting. For large transfers, prefer `Bash + scp` in background.
- `transfer_size_cap` is checked via `os.path.getsize()` before transfer begins; nothing is transferred if the file is too large.

## Bandwidth/latency profile

- **Transfer size:** equal to the local file's byte length, subject to SSH compression.
- **Round-trips:** one SFTP session reused from the connection; one or more SFTP `mkdir` round-trips for parent path creation; one SFTP `put` (which itself involves multiple data packets but is one logical operation).
- **Blocks the conversation** for the duration of the transfer. For files where the transfer time matters, use `Bash("scp ...", run_in_background=true)`.

## See also

- [Download](./download.md) — the inverse
- [Write](./write.md) — text-only, in-memory content rather than from a local file path
- [Bash](./bash.md) — for the `scp` + `run_in_background=true` pattern
- [How-to: run long background jobs](../../how-to/run-long-background-jobs.md)
- Spec — *not in spec; added in v0.1.1*
