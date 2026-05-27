# Error wording catalog

> 中文版本：[errors.zh.md](./errors.zh.md)

Every tool returns a string. Failure cases return strings starting with `"Error: "`. Below is the complete catalog with the exact wording, the tool that emits it, and the triggering condition.

This wording is API-stable — consumers (especially Claude Code's error-recovery logic) may pattern-match against these strings. Changes to error wording are breaking changes.

## By tool

### Read

| Trigger | Returned string |
|---------|-----------------|
| `offset` argument is less than 1 | `Error: offset must be >= 1, got <offset>` |
| `limit` argument is less than 1 | `Error: limit must be >= 1, got <limit>` |
| File does not exist (sed stderr contains "No such file" or "cannot open") | `Error: File not found: <file_path>` |
| `sed` exits non-zero for any other reason | `Error: <stderr>` — stderr from the remote `sed` command, stripped; falls back to `Error: unknown error reading file` when stderr is empty |

### Write

| Trigger | Returned string |
|---------|-----------------|
| User lacks write permission on `<file_path>` or its parent (SFTP `PermissionError`, or `IOError` with `errno=EACCES`) | `Error: Permission denied: <file_path>` |
| Other SFTP write failure (target is a directory, disk full, invalid path) | `Error: <message>` — the underlying exception's `str()`, or the exception class name if `str()` is empty |

### Edit

| Trigger | Returned string |
|---------|-----------------|
| File does not exist (SFTP `IOError` on open) | `Error: File not found: <file_path>` |
| `old_string` not found in file (zero occurrences, `replace_all=False`) | `Error: old_string not found in <file_path>` |
| `old_string` not found in file (zero occurrences, `replace_all=True`) | `Error: old_string not found in <file_path>` |
| `old_string` found more than once and `replace_all=False` | `Error: old_string found <N> times in <file_path> (lines <L1, L2, ...>). Provide more context to match uniquely, or set replace_all=true to replace all.` |

### MultiEdit

| Trigger | Returned string |
|---------|-----------------|
| `edits` list is empty | `Error: edits list is empty` |
| File does not exist (SFTP `IOError` on open) | `Error: File not found: <file_path>` |
| Edit N's `old_string` not found (zero occurrences, `replace_all=False`) | `Error: edit #<N>: old_string not found` |
| Edit N's `old_string` not found (zero occurrences, `replace_all=True`) | `Error: edit #<N>: old_string not found` |
| Edit N's `old_string` found more than once and `replace_all=False` | `Error: edit #<N>: old_string found <M> times (lines <L1, L2, ...>). Provide more context or set replace_all=true.` |

### MultiRead

| Trigger | Returned string |
|---------|-----------------|
| `reads` list is empty | `Error: reads list is empty` |
| Remote command exits non-zero and stdout is empty | `Error: <stderr>` — stderr from the remote shell, stripped; falls back to `Error: multi_read failed` when stderr is empty |

Per-file not-found is not an `"Error: ..."` string — individual missing files are reported inline as `===FILE: <path>===\nNOT_FOUND\n\n` within the combined output.

### FileStat

| Trigger | Returned string |
|---------|-----------------|
| `file_paths` is an empty list | `Error: file_paths is empty` |

Per-path failures are not `"Error: ..."` strings — they are reported inline within the result:
- Path does not exist: `<path>: exists=false`
- Permission denied on stat: `<path>: error=permission_denied`

### Bash

| Trigger | Returned string |
|---------|-----------------|
| Foreground command exceeds timeout | `Error: Command timed out after <timeout>s on <host>` |
| Background launch times out (10 s internal limit) | `Error: failed to launch background task on <host> (timeout)` |
| Background launch succeeds but `BG_PID=<n>` not found in output | `Error: failed to start background task on <host>. Output: <first 500 chars of output>` |

### Glob

| Trigger | Returned string |
|---------|-----------------|
| `find` command exits with a code other than 0 or 1 (e.g., permission error, invalid path) | `Error: <stderr>` — stderr from the remote `find` command, stripped |

No-match is not an error: `"No files found matching pattern"` is returned (no `"Error: "` prefix).

### Grep

| Trigger | Returned string |
|---------|-----------------|
| `output_mode` is not one of `"content"`, `"files_with_matches"`, `"count"` | `Error: invalid output_mode: <output_mode>. Must be one of ('content', 'files_with_matches', 'count').` |
| `grep` exits with code 2 (grep-level error, e.g., invalid regex, unreadable path) | `Error: <stderr>` — stderr from the remote `grep` command, stripped |

No-match (exit code 1 or empty stdout) is not an error: `"No matches found"` is returned (no `"Error: "` prefix).

### Feedback

| Trigger | Returned string |
|---------|-----------------|
| `category` is not `"bug"` or `"enhancement"` | `Error: category must be 'bug' or 'enhancement', got <category>` (value is `repr`-formatted, e.g., `'other'`) |
| `summary` is blank or whitespace-only | `Error: summary cannot be empty` |

### Upload

| Trigger | Returned string |
|---------|-----------------|
| `local_path` does not exist | `Error: Local file not found: <local_path>` |
| `local_path` is a directory | `Error: Local path is a directory, not a file: <local_path>` |
| Local file size > `transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Remote write denied | `Error: Permission denied: <remote_path>` |
| Other SFTP failure | `Error: <message>` |

### Download

| Trigger | Returned string |
|---------|-----------------|
| Local parent directory missing | `Error: Local parent directory not found: <dir>` |
| `remote_path` does not exist | `Error: Remote file not found: <remote_path>` |
| `remote_path` is a directory | `Error: Remote path is a directory, not a file: <remote_path>` |
| Remote file size > `transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Local write denied | `Error: Permission denied: <local_path>` |
| Other SFTP failure | `Error: <message>` |

### RemoteInfo

RemoteInfo cannot fail — it returns the in-memory config. No error strings.

### Server / dispatch

| Trigger | Returned string |
|---------|-----------------|
| Tool name not recognized by `_raw_dispatch` | `Error: unknown tool: <name>` |
| SSH connection drops and reconnect fails | `Error: SSH connection to <host> lost and reconnect failed: <reason>` |
| SSH connection drops, reconnect succeeds, but the retried tool call raises an exception | `Error: <exception message>` |

## Cross-cutting notes

- **File-not-found wording differs by implementation path.** Read uses `sed` over `exec` and detects missing files by inspecting stderr text (`"No such file"`, `"cannot open"`). Edit, MultiEdit, and Write use SFTP and detect missing files via `IOError`. The returned string is the same (`Error: File not found: <path>`), but the detection mechanism differs.
- **MultiEdit per-edit errors embed an edit index.** The format `Error: edit #<N>: ...` uses 1-based numbering. On the first failing edit, the operation aborts and the file is left unchanged. Subsequent edits (after the failing one) are not attempted.
- **MultiRead per-file not-found is inline, not an error prefix.** Individual `NOT_FOUND` entries are embedded in the combined output block, not returned as `"Error: ..."` strings. Only whole-command failures produce a top-level `"Error: ..."`.
- **FileStat per-path failures are inline.** `exists=false` and `error=permission_denied` appear as lines in the normal result, not as top-level `"Error: ..."` strings. Only an empty `file_paths` list produces a top-level error.
- **Bash output truncation is not an error.** When output exceeds `bash_output_cap`, the output is truncated in-place with `\n... [truncated to <N> bytes]` appended. This is part of the success return value.
- **Read output truncation is not an error.** When the formatted output exceeds `read_size_cap`, a `\n... [truncated to <N> bytes]` suffix is appended. This is part of the success return value.
- **The reconnect WARNING is not an error prefix.** When the SSH connection drops and auto-reconnect succeeds, the tool result is prefixed with `[WARNING] SSH connection to <host> was lost and has been re-established. ...` — this is prepended to whatever the tool returned (success or error), and does not replace it.
- **Write SFTP exceptions are not caught at the tool level.** Permission denied and similar failures from `sftp.file()` propagate to the server retry path, where they become `Error: <exception message>` with the raw Python exception text.
