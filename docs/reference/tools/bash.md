# Bash

> 中文版本：[bash.zh.md](./bash.zh.md)

Execute a shell command on the remote host, either as a foreground (blocking) call or as a detached background process with panel tracking.

## Schema

```json
{
  "type": "object",
  "properties": {
    "command":           {"type": "string"},
    "description":       {"type": "string", "default": ""},
    "timeout":           {"type": "number", "default": 120},
    "run_in_background": {"type": "boolean", "default": false},
    "log_path": {
      "type": "string",
      "description": "Background only. Absolute remote path for stdout+stderr. Defaults to ~/.cache/remote-mcp-<sid>-<id>.log. Parent dirs auto-created."
    },
    "name": {
      "type": "string",
      "description": "Background only. Job alias for panel reference. Defaults to bg-<uuid12>. Must be unique among active jobs. Pattern: [A-Za-z0-9_.-]+ length 1-64."
    }
  },
  "required": ["command"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `command` | string | yes | — | Shell command to execute on the remote host. Passed verbatim to bash — no extra quoting is applied. |
| `description` | string | no | `""` | Brief description (CC native compat). When `run_in_background=true`, also stored as the task description in the panel (truncated to 500 chars). |
| `timeout` | number | no | `120` | Foreground timeout in seconds. Ignored when `run_in_background=true`. |
| `run_in_background` | boolean | no | `false` | When `true`, launches as a detached panel-tracked background job and returns immediately. |
| `log_path` | string | no | `~/.cache/remote-mcp-<sid>-<id>.log` | Background only. Explicit remote log path. Parent dirs created via `mkdir -p`. If a non-directory exists at the parent path, returns Error. |
| `name` | string | no | `bg-<uuid12>` | Background only. Human-readable job name. Collision with active (non-archived) job returns Error. |

## Returns

A string. The format depends on `run_in_background`.

### Foreground output (`run_in_background=false`)

**On success (exit code 0):**

```
<command output>

[host=<name> cwd=<cwd>]
```

**On success with non-zero exit code:**

```
<command output>
[Exit code: <N>]

[host=<name> cwd=<cwd>]
```

- `<name>` is the host name from the config.
- `<cwd>` is the configured remote cwd — stable across all calls.
- `\r\n` sequences are normalized to `\n`; bare `\r` characters are stripped.
- Output is capped at `bash_output_cap` (default 100 KB); truncated output ends with `\n... [truncated to <N> bytes]`.

**On error:** one of the strings listed in [Error wording](#error-wording).

### Background output (`run_in_background=true`)

Returns immediately after the background process is confirmed (see [Synchronous PID confirmation](#synchronous-pid-confirmation)):

```
Started background task.
  id: 17
  name: x86_python_build
  log_path: /home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log
  pid: 1259443
  started_at: 2026-05-31T08:40:53Z

[host=<name> cwd=<cwd>]
```

Fields:
- `id` — monotonically increasing integer within this session + host. Use with `Jobs(id=N)`, `JobKill(id=N)`, `JobArchive(id=N)`.
- `name` — the alias passed in, or the auto-generated `bg-<uuid12>`.
- `log_path` — absolute path to the merged stdout+stderr log on the remote.
- `pid` — PID of the `setsid`-spawned process group leader. `kill -- -<pid>` terminates the entire tree.
- `started_at` — ISO-8601 UTC timestamp from the remote shell.

### Synchronous PID confirmation

The tool does not return until the remote PID is confirmed. If the exec response is lost (network fault):

1. The tool immediately falls back to an SFTP read of `~/.cache/remote-mcp-<sid>-<id>-pid`.
2. If the file is present and contains a valid integer, launch succeeds (with a NOTE that `started_at` is approximated from the pid file mtime).
3. If both fail, the task is NOT entered into the panel and an Error is returned with recovery instructions. The failed panel entry is cleaned up locally.

This guarantees every panel entry corresponds to a confirmed remote process. See spec §5.3.4 for full details.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| Foreground command times out | `Error: Command timed out after <timeout>s on <name>` |
| `name` doesn't match `^[A-Za-z0-9_.-]{1,64}$` | `Error: invalid job name 'X': must match ^[A-Za-z0-9_.-]{1,64}$` |
| `name` already in active panel | `Error: job name 'X' already in active panel; archive the old one with JobArchive(name='X') or pick a different name` |
| `log_path` parent exists but is not a directory | `Error: log_path parent ... exists but is not a directory; cannot mkdir -p` |
| Background PID unconfirmable (exec lost + SFTP fallback failed) | `Error: background launch for '<name>' (id=<id>) on <host> could not be confirmed. ...` (with recovery steps) |

## Behavior notes

- **Non-persistent shell**: each call is a fresh `bash --noprofile --norc -c "..."`. `cd`, `export`, `source venv/bin/activate` do NOT survive across calls — chain inline with `&&` if needed.
- **Foreground shell wrap**: `bash --noprofile --norc -c 'source <snapshot_path> 2>/dev/null || true; <user_command>' </dev/null`. The snapshot provides PATH, aliases, functions, and `cd <cwd>`.
- **Background shell wrap**: `( setsid nohup bash --noprofile --norc -c 'source <snapshot_path> 2>/dev/null || true; <user_command>' > <log_path> 2>&1 </dev/null & PID=$!; echo $PID > ~/.cache/remote-mcp-<sid>-<id>-pid; ... echo "BG_PID=$PID" ... )`. The `setsid` creates a new session — the background process survives SSH channel close, laptop suspend, and MCP server restart.
- **Snapshot replay**: the remote `~/.bashrc` is loaded once at SSH connect time. Subsequent calls source the captured snapshot. Changes to `~/.bashrc` after connect do not take effect until reconnect.
- **Configured cwd**: each call starts at the configured `cwd`. The snapshot ends with `cd <cwd> || exit 1`.
- **No PTY**: stdin is `/dev/null`. `srun`, `cat` (no args), and other stdin-readers don't hang. Interactive tools (`vim`, `top`, REPLs) are NOT supported.
- **Timeout (foreground)**: closes the SSH channel, sending SIGHUP to the remote command's session. Partial stdout is included in the error output.
- **Background log**: stdout + stderr merged into `log_path`. The file is NOT cleaned on MCP server exit (deliberate — `/tmp` is cleared on reboot; `~/.cache` is permanent).
- **Output**: combined stdout + stderr. Trailing `[Exit code: N]` on non-zero exits. Capped at `bash_output_cap` (default 100 KB).

## Background task management workflow

```
# Launch
Bash(run_in_background=True, name="build", command="bash ~/build.sh > ~/build.log 2>&1")
# → id: 3, pid: 12345, log_path: /home/user/.cache/remote-mcp-abc-3.log

# Check status (refreshes panel state from remote)
Jobs(name="build")

# Read log incrementally
Read("/home/user/.cache/remote-mcp-abc-3.log", offset=50)

# Kill
JobKill(name="build")

# After confirming stopped / result reviewed, archive
JobArchive(name="build")
```

## Bandwidth/latency profile

- **Foreground:** one exec round-trip per call. Output crosses the network once; use `head`/`tail` server-side for large outputs.
- **Background launch:** two exec round-trips (one `mkdir -p`, one wrap), plus an SFTP read only if exec response is lost.
- **Background poll:** each `Jobs` list call = at most one batched exec regardless of job count. Each `Jobs(name=X)` single-task call = 1–4 remote ops depending on state and status script presence.

## See also

- [Jobs](./jobs.md) — list and query panel tasks
- [JobKill](./job-kill.md) — send a kill signal to a panel task
- [JobArchive](./job-archive.md) — archive a finished panel task
- [JobScript](./job-script.md) — attach a status script to a panel task
- [Read](./read.md) — poll background task log file output
- [FileStat](./file-stat.md) — check log file size before reading
- Spec §5
