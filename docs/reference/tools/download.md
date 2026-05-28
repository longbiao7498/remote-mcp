# Download

> 中文版本：[download.zh.md](./download.zh.md)

Pull a remote file to the local machine via SFTP. Binary-safe.

**On Linux/macOS, prefer `Bash("scp <user>@<host>:<remote> <local>", run_in_background=true)`** — non-blocking, any size, resumable with `rsync`. Download is primarily for Windows users without `scp` in PATH.

## Schema

```json
{
  "type": "object",
  "properties": {
    "remote_path": {"type": "string"},
    "local_path": {"type": "string"}
  },
  "required": ["remote_path", "local_path"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `remote_path` | string | yes | — | Absolute remote path, or relative to the configured cwd (same as Read/Write/etc.). |
| `local_path` | string | yes | — | Absolute LOCAL path or with ~ (expanded via `os.path.expanduser`). NOT subject to the configured remote cwd. Parent directory must already exist (not auto-created). Overwrites if exists. |

## Returns

A string.

**On success:** `Successfully downloaded <N> bytes from <remote_path> to <local_path>` where `<N>` is the remote file's byte length.

**On error:** see [Error wording](#error-wording).

The MCP server appends `\n\n[host=X cwd=Y]` to every output (success and error). The tool's own output is everything before that suffix.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| Local parent directory does not exist | `Error: Local parent directory not found: <dir>` |
| `remote_path` does not exist (SFTP `stat` raises `IOError`) | `Error: Remote file not found: <remote_path>` |
| `remote_path` is a directory | `Error: Remote path is a directory, not a file: <remote_path>` |
| Remote file size > `conn.config.transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Local write denied (`PermissionError` or `IOError` with `errno=EACCES`) | `Error: Permission denied: <local_path>` |
| Other SFTP failure | `Error: <message>` |

## Behavior notes

- Uses paramiko's `sftp.get(remote, local)` which streams the file.
- Remote `stat()` is called before the transfer to enforce the size cap and to give a clean "Remote file not found" error rather than a cryptic mid-transfer failure.
- The local parent directory must exist; Download does NOT auto-create local directories (asymmetric with Upload, which auto-creates remote dirs).
- Local file is written in binary mode.
- Blocks until completion; no progress reporting.
- **Partial files on mid-transfer failure**: if the network dies or the remote disconnects partway through a `get`, paramiko may leave a partial file at `local_path`. Download does NOT auto-delete it — unconditional deletion would destroy any pre-existing file the user had at that path. On an `Error:` return mid-transfer, treat the local target as potentially corrupt. For resumable transfers, use `Bash("rsync --partial --inplace ...", run_in_background=true)` instead.

## Bandwidth/latency profile

- **Transfer size:** equal to the remote file's byte length, subject to SSH compression.
- **Round-trips:** 1 SFTP `stat` (cap check) + 1 SFTP `get`.
- **Blocks the conversation** for the transfer duration. For large files, use `Bash + scp` in background.

## See also

- [Upload](./upload.md) — the inverse
- [Read](./read.md) — server-side line slicing; doesn't write the file locally
- [Bash](./bash.md) — for `scp` + `run_in_background=true`
- [How-to: run long background jobs](../../how-to/run-long-background-jobs.md)
- Spec — *not in spec; added in v0.1.1*
