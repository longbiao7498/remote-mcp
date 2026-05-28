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
<command output>

[host=<name> cwd=<cwd>]
```

**On success with non-zero exit code:**

```
<command output>
[Exit code: <N>]

[host=<name> cwd=<cwd>]
```

- `<name>` is the host name from the config (the value of `conn.config.name`).
- `<cwd>` is the configured remote cwd — stable across all calls.
- `\r\n` sequences in the output are normalized to `\n`; bare `\r` characters are stripped.
- Output is capped at `conn.config.bash_output_cap` bytes (default 100 KB). When truncated, the output ends with `\n... [truncated to <N> bytes]`.

**On error:** one of the strings listed in [Error wording](#error-wording).

### Background output (`run_in_background=true`)

Returns immediately after the background process is launched:

```
Started background task.
  PID: <pid>
  Log: <log_path>

To check status:    Bash("kill -0 <pid> && echo running || echo done")
To read new output: Read("<log_path>", offset=<last_line+1>)
To stop gracefully: Bash("kill -TERM -- -<pid>")
To force stop:      Bash("kill -KILL -- -<pid>")

[host=<name> cwd=<cwd>]
```

- `<pid>` is the PID of the `setsid`-spawned bash. Because `setsid` creates a new process group with PID = PGID, `kill -- -<pid>` kills the entire process tree.
- `<log_path>` is `/tmp/rmcp-bg-<12-hex-uuid>.log`. Stdout and stderr of the background command are merged into this file. The file is not cleaned up when the MCP server exits; `/tmp` is cleared on reboot.
- The four hint lines are literal strings in the returned output. Their exact format is shown above.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| Foreground command times out | `Error: Command timed out after <timeout>s on <name>` |
| Background launch does not emit `BG_PID=<n>` | `Error: failed to start background task on <name>. Output: <first 500 chars of output>` |

## Behavior notes

- **Non-persistent shell**: each call is a fresh `bash --noprofile --norc -c "..."`. `cd`, `export`, `source venv/bin/activate` do NOT survive across calls — chain inline with `&&` if needed.
- **Snapshot replay**: the remote `~/.bashrc` is loaded once at SSH connect time; subsequent Bash calls `source` the dumped snapshot, restoring PATH, aliases, functions, exported vars. Updates to `~/.bashrc` made after connect do NOT take effect until reconnect.
- **Configured cwd**: each Bash invocation starts at the configured `cwd` (`--cwd /opt/app`, default `$HOME`). The snapshot ends with `cd <cwd> || exit 1`.
- **No PTY**: stdin is `/dev/null`. `srun`, `cat` (no args), and other stdin-readers don't hang. Interactive tools (`vim`, `top`, REPLs) are NOT supported.
- **Timeout**: closes the SSH channel, which sends SIGHUP to the remote command's session — kills the command and all its children. Partial stdout collected before timeout is included in the error output.
- **Background (`run_in_background=true`)**: launches `setsid nohup bash --noprofile --norc -c "source <snapshot>; ..." > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`. Sources the snapshot so the configured cwd and PATH are in effect. Returns PID + log path + 4 manipulation commands. Use `kill -- -<pid>` to kill the whole process group. If the launch response is lost due to network failure, the remote process may still be running. Recover its PID via `Bash("cat /tmp/rmcp-bg-*.pid")` — the pidfile is written by remote shell before the echo that could be lost, sharing the same `<uuid>` as the log file.
- **Output**: combined stdout + stderr. Trailing `[Exit code: N]` line on non-zero exits. Capped at `bash_output_cap` (default 100 KB). The unified `[host=X cwd=Y]` suffix is appended by the MCP server, not the tool.

## Bandwidth/latency profile

- **Foreground:** output bytes cross the network once. Large outputs should be piped through `head`/`tail` server-side. The 100 KB cap is a safety rail, not a substitute for server-side filtering.
- **Background:** only the `BG_PID=<n>` line crosses the network at launch. Subsequent output is polled via [Read](./read.md) on the log file — each poll transfers only the new lines requested via `offset`.
- **Round-trips:** foreground = one logical round-trip per call (single exec_command + channel drain); background launch = one round-trip, subsequent polls = one round-trip each via Read.

## See also

- [Read](./read.md) — poll background task log file output
- [FileStat](./file-stat.md) — check log file size before reading
- [Glob](./glob.md) — find files without running a shell find command
- [Grep](./grep.md) — search file content server-side
- Spec §5.3.7
