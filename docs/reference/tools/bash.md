# Bash

> 中文版本：[bash.zh.md](./bash.zh.md)

Execute a shell command on the remote host, either in the persistent foreground session or as a detached background process group.

## Schema

```json
{
  "type": "object",
  "properties": {
    "command":           {"type": "string"},
    "description":       {"type": "string", "default": ""},
    "timeout":           {"type": "number", "default": 120},
    "run_in_background": {"type": "boolean", "default": false}
  },
  "required": ["command"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `command` | string | yes | — | Shell command to execute on the remote host. Passed verbatim to bash — no extra quoting is applied. |
| `description` | string | no | `""` | Informational label. Not used internally; kept for schema compatibility with Claude Code's native Bash tool. |
| `timeout` | number | no | `120` | Foreground timeout in seconds. Ignored when `run_in_background=true`. If omitted, the value from `conn.config.bash_timeout_default` is used (default `120`). |
| `run_in_background` | boolean | no | `false` | When `true`, launches the command as a detached background process group and returns immediately. |

## Returns

A string. The format depends on `run_in_background`.

### Foreground output (`run_in_background=false`)

**On success (exit code 0):**

```
[host=<name> cwd=<cwd>]
<command output>
```

**On success with non-zero exit code:**

```
[host=<name> cwd=<cwd>]
<command output>
[Exit code: <N>]
```

- `<name>` is the host name from the config (the value of `conn.config.name`).
- `<cwd>` is the working directory after the command completes, captured from the sentinel line.
- `\r\n` sequences in the output are normalized to `\n`; bare `\r` characters are stripped.
- Output is capped at `conn.config.bash_output_cap` bytes (default 100 KB). When truncated, the output ends with `\n... [truncated to <N> bytes]`.

**On error:** one of the strings listed in [Error wording](#error-wording).

### Background output (`run_in_background=true`)

Returns immediately after the background process is launched:

```
[host=<name> cwd=<cwd>]
Started background task.
  PID: <pid>
  Log: <log_path>

To check status:    Bash("kill -0 <pid> && echo running || echo done")
To read new output: Read("<log_path>", offset=<last_line+1>)
To stop gracefully: Bash("kill -TERM -- -<pid>")
To force stop:      Bash("kill -KILL -- -<pid>")
```

- `<pid>` is the PID of the `setsid`-spawned bash. Because `setsid` creates a new process group with PID = PGID, `kill -- -<pid>` kills the entire process tree.
- `<log_path>` is `/tmp/rmcp-bg-<12-hex-uuid>.log`. Stdout and stderr of the background command are merged into this file. The file is not cleaned up when the MCP server exits; `/tmp` is cleared on reboot.
- The four hint lines are literal strings in the returned output. Their exact format is shown above.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| Foreground command times out | `Error: Command timed out after <timeout>s on <name>` |
| Background launch wrapper times out (10 s internal limit) | `Error: failed to launch background task on <name> (timeout)` |
| Background launch does not emit `BG_PID=<n>` | `Error: failed to start background task on <name>. Output: <first 500 chars of output>` |

## Behavior notes

- **Persistent session.** Foreground calls share a single long-lived bash process for the lifetime of the SSH connection. Shell state (current directory, exported variables, shell functions) persists across foreground calls. Background calls also use the session to launch the wrapper, but the background process itself is detached.
- **Background process isolation.** The background command is wrapped in `setsid nohup bash -c <cmd> > <log> 2>&1 </dev/null &`. `setsid` creates a new session, making the spawned bash the process group leader (PID = PGID). Because the persistent session runs with `set +m` (job control disabled), a plain `&` would not create a new process group; `setsid` is required for `kill -- -<pid>` to work correctly.
- **Timeout behavior (foreground).** On timeout, the tool sends Ctrl-C (`\x03`) to the remote bash, then returns the error string. The bash session itself remains alive for subsequent calls.
- **Output cap (foreground).** The cap is applied after `\r\n` normalization. The `[Exit code: N]` suffix (if any) is appended before the cap check.
- **No interactive commands.** Commands requiring a TTY (`vim`, `top`, REPLs, `sudo` with password prompt) do not work. The bash session has `TERM=dumb` and no PTY.
- **`description` parameter.** Accepted and ignored. It exists so tool calls written for Claude Code's native Bash work without modification.
- **SSH reconnect.** If the SSH connection is rebuilt mid-session, shell state (cwd, env) is reset. The caller in `server.py` prefixes the next tool result with a `[WARNING]` describing the reconnect. See [CLAUDE.md](../../../CLAUDE.md) for the exact warning text.

## Bandwidth/latency profile

- **Foreground:** output bytes cross the network once. Large outputs should be piped through `head`/`tail` server-side. The 100 KB cap is a safety rail, not a substitute for server-side filtering.
- **Background:** only the `BG_PID=<n>` line crosses the network at launch. Subsequent output is polled via [Read](./read.md) on the log file — each poll transfers only the new lines requested via `offset`.
- **Round-trips:** foreground = one logical round-trip per call (sentinel-based); background launch = one round-trip, subsequent polls = one round-trip each via Read.

## See also

- [Read](./read.md) — poll background task log file output
- [FileStat](./file-stat.md) — check log file size before reading
- [Glob](./glob.md) — find files without running a shell find command
- [Grep](./grep.md) — search file content server-side
- Spec §5.3.7
