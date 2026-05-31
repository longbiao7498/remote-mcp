# JobScript

> 中文版本：[job-script.zh.md](./job-script.zh.md)

Attach (or clear) a custom bash status script to a panel-tracked job. The script runs automatically each time `Jobs(name=X)` or `Jobs(id=N)` is called in single-task mode.

## Schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Job name. Mutually exclusive with id."
    },
    "id": {
      "type": "integer",
      "description": "Job id. Mutually exclusive with name."
    },
    "script": {
      "type": "string",
      "description": "Bash script body. Stored locally at ~/.local/share/remote-mcp/jobpane/<sid>/<host>/<id>-status.sh (source of truth) and uploaded to remote ~/.cache/remote-mcp-<sid>-<id>-status.sh (cache; auto-reuploaded by Jobs if missing). Runs server-side on each Jobs(name=X) single-task query. Pass empty string '' to clear (deletes local source only; remote cache left in place but no longer referenced). The script runs via 'bash --noprofile --norc' with snapshot sourced; reference $PID via 'cat ~/.cache/remote-mcp-<sid>-<id>-pid' or pgrep your own pattern."
    },
    "timeout": {
      "type": "integer",
      "description": "Required. Seconds. Pick based on what your script does: simple pgrep+tail+ls=5; reading large log on shared FS=30; calling squeue/kubectl/network services=60. Timeout triggers immediate channel close. Stored in meta.json as script_timeout; reused on every Jobs(name=X) call."
    }
  },
  "required": ["script", "timeout"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | no | — | Job alias. Mutually exclusive with `id`. One of `name` or `id` required. |
| `id` | integer | no | — | Job id. Mutually exclusive with `name`. |
| `script` | string | yes | — | Script body. Pass `""` to clear the script. |
| `timeout` | integer | yes | — | Run timeout in seconds. No default — agent must think about what the script does. Stored in meta and reused by every subsequent `Jobs(name=X)` call. |

Both `script` and `timeout` are always required — `script=""` with a `timeout` value still clears the script (timeout ignored on clear).

## Returns

### Script attached successfully (exit_code 0)

```
Status script attached to 'x86_python_build' (id=17).
First-run validation:
  exit_code: 0
  elapsed_sec: 1
  stdout: |
    pid=1259443 alive
    progress=26/42
  stderr: (empty)

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Script attached with non-zero exit on first run

```
Status script attached to 'x86_python_build' (id=17). NOTE: first-run
exited with non-zero code. The script is still attached (non-zero exit
may be intentional, e.g. 'task not yet in expected phase'). Verify the
output below matches your intent; call JobScript again with the same
name to replace.

First-run validation:
  exit_code: 2
  elapsed_sec: 1
  stdout: ...
  stderr: ...

[host=tjcs_ex_ln3 cwd=/home/user]
```

### First-run timed out — script rejected

```
Error: status script first-run timed out after 30s on tjcs_ex_ln3.
Script has been removed (both local source and remote cache); status
script for 'x86_python_build' is now empty. Likely causes: script
logic too slow, or timeout too tight. Adjust and call JobScript again.

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Script cleared (`script=""`)

```
Status script cleared for 'x86_python_build' (id=17).
(Remote cache file at ~/.cache/remote-mcp-<sid>-17-status.sh is left
in place but no longer referenced; it will be overwritten if you
attach a new script.)

[host=tjcs_ex_ln3 cwd=/home/user]
```

## Behavior notes

- **Local source of truth**: the script body is written to `~/.local/share/remote-mcp/jobpane/<sid>/<host>/<id>-status.sh` on the MCP host. The remote file (`~/.cache/remote-mcp-<sid>-<id>-status.sh`) is a cache.
- **Auto-reupload**: if the remote cache is missing when `Jobs(name=X)` runs the script, it is automatically reuploaded from the local source. External cleanup of `~/.cache/` does not break the script permanently.
- **First-run validation**: on `script != ""`, JobScript uploads the script and runs it once. Timeout on first run = script rejected and cleaned up (both local and remote). Non-zero exit = script accepted with a notice (the agent verifies the output is intentional).
- **Clear semantics**: `script=""` deletes the local source file and sets `meta.script_timeout = null`. The remote cache is left in place (it will be overwritten on next `JobScript` set). The cleared script is not run by subsequent `Jobs` calls.
- **Script environment**: the script runs via `exec_with_snapshot`, so the snapshot (PATH, aliases, configured cwd) is in effect. To reference the job's PID in the script: `cat ~/.cache/remote-mcp-<sid>-<id>-pid` or `pgrep -f <pattern>`.
- **Timeout reuse**: the `timeout` value is stored in `meta.script_timeout` and reused by every subsequent `Jobs(name=X)` single-task call. To change the timeout, call `JobScript` again with the same script and a new timeout.
- **Archived tasks**: JobScript rejects requests for archived tasks.

## Design intent

Status scripts let the agent get rich, structured status from a single `Jobs(name=X)` call instead of a multi-step `pgrep + tail + ls + squeue` chain. A well-written status script outputs exactly the fields the agent needs to decide "still running / done / needs attention" — without transferring large log files over the wire.

Example script for a Python build:

```bash
#!/bin/bash
PID=$(cat ~/.cache/remote-mcp-XXXX-17-pid 2>/dev/null)
if kill -0 "$PID" 2>/dev/null; then
    echo "pid=$PID alive"
fi
PROG=$(grep -c 'Compiling' ~/build.log 2>/dev/null || echo 0)
echo "progress=$PROG objects compiled"
ls ~/install/Python-3.13.4/bin/python3 2>/dev/null && echo "artifact=ready" || echo "artifact=not_yet"
```

## Routing

JobScript is in `NO_RETRY_TOOLS` — it uploads a file and runs it; both are non-idempotent side effects that should not be auto-retried.

## See also

- [Jobs](./jobs.md) — runs the attached status script in single-task mode
- [Bash](./bash.md) — launch background tasks
- Spec §9
