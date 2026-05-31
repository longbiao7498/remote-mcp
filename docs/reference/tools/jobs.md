# Jobs

> 中文版本：[jobs.zh.md](./jobs.zh.md)

Query the background task panel: list active jobs with live state, or inspect a single job in detail.

## Schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Job name to query (single-task mode). Mutually exclusive with id."
    },
    "id": {
      "type": "integer",
      "description": "Job id to query (single-task mode). Mutually exclusive with name."
    },
    "filter": {
      "type": "string",
      "enum": ["stopped_unprocessed", "stuck_kill", "zombies"],
      "description": "List-mode filter. stopped_unprocessed: state in {stopped, killed} and not archived (finished tasks awaiting result review). stuck_kill: state == kill_failed AND kill_attempts >= 3 AND not archived. zombies: archived with zombie=true."
    }
  }
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | no | — | Job alias. Triggers single-task mode. Mutually exclusive with `id`. |
| `id` | integer | no | — | Job id. Triggers single-task mode. Mutually exclusive with `name`. |
| `filter` | string | no | — | List-mode filter. Cannot be combined with `name` or `id`. |

All parameters are optional. Calling `Jobs()` with no arguments lists all active (non-archived) jobs.

## State machine

The real state of a job is derived each time Jobs observes it:

| State | Derivation |
|-------|-----------|
| `running` | `kill -0 <pid>` succeeds AND `kill_requested_at` is null |
| `stopped` | `kill -0 <pid>` fails AND `kill_requested_at` is null |
| `killed` | `kill -0 <pid>` fails AND `kill_requested_at` is non-null |
| `kill_failed` | `kill -0 <pid>` succeeds AND `kill_requested_at` is non-null (kill sent but process alive) |

**Terminal states**: `stopped` and `killed` are terminal — once observed and cached, Jobs skips re-observation for those tasks (no `kill -0` issued). This avoids false positives from PID reuse after the original process exits.

**State caching**: Jobs writes the observed state back to the local `<id>-meta.json` after each observation. `JobArchive` reads this cache directly (no remote op).

## Filter values

| Filter | Semantics |
|--------|-----------|
| _(none)_ | All active (non-archived) jobs |
| `stopped_unprocessed` | state ∈ {stopped, killed}, not archived — tasks that finished; read the log and archive them |
| `stuck_kill` | state == kill_failed AND kill_attempts ≥ 3, not archived — tasks resisting kill; escalate to `kill -KILL` or `JobArchive(as_zombie=True)` |
| `zombies` | archived with `zombie=true` — tasks you gave up on; the remote process may still be running |

## Returns

### List mode

```
2 active jobs (filter=none):

[
  {
    "id": 17,
    "name": "x86_python_build",
    "description": "Python 3.13.4 build on x86 login node",
    "host": "tjcs_ex_ln3",
    "pid": 1259443,
    "log_path": "/home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log",
    "state": "running",
    "started_at": "2026-05-31T08:40:53Z",
    "elapsed_sec": 14523,
    "kill_requested_at": null,
    "kill_attempts_count": 0,
    "zombie": false
  },
  ...
]

[host=tjcs_ex_ln3 cwd=/home/user]
```

Fields:

| Field | Description |
|-------|-------------|
| `id` | Panel id; use with `Jobs(id=N)`, `JobKill(id=N)`, `JobArchive(id=N)` |
| `name` | Job alias |
| `description` | Description passed at launch |
| `host` | Remote host name |
| `pid` | Remote process PID (group leader; `kill -- -<pid>` kills the tree) |
| `log_path` | Merged stdout+stderr log on the remote; feed to `Read` |
| `state` | State freshly observed this call (§ state machine above) |
| `started_at` | ISO-8601 UTC launch time |
| `elapsed_sec` | `remote_now - started_at_unix`. For stopped/killed tasks this includes idle time after stop |
| `kill_requested_at` | Timestamp of most recent kill attempt; null = never killed |
| `kill_attempts_count` | Total kill attempts; ≥ 3 with state kill_failed = stuck |
| `zombie` | true only when `filter=zombies` |

### Single-task mode

Single-task mode includes additional fields and runs the status script if attached:

```json
{
  "id": 17,
  "name": "x86_python_build",
  "description": "Python 3.13.4 build on x86 login node",
  "command": "bash ~/scripts/login_x86_python.sh",
  "log_path": "/home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log",
  "host": "tjcs_ex_ln3",
  "pid": 1259443,
  "state": "running",
  "started_at": "2026-05-31T08:40:53Z",
  "elapsed_sec": 14523,
  "kill_requested_at": null,
  "kill_attempts": [],
  "archived_at": null,
  "zombie": false,
  "status_script_output": {
    "stdout": "pid=1259443 alive\nprogress=26/42\n",
    "stderr": "",
    "exit_code": 0,
    "elapsed_sec": 1,
    "error": null
  }
}
```

Extra fields vs. list mode:

| Field | Description |
|-------|-------------|
| `command` | Original command string passed at launch |
| `kill_attempts` | Full attempt list with `{at, at_unix, kill_cmd, exit_code, stdout, stderr}` per entry |
| `archived_at` | Non-null for archived tasks queried by id |
| `status_script_output` | null if no script attached; otherwise stdout/stderr/exit_code/elapsed_sec/error |

`status_script_output.error` is set when the script times out or has an SSH-layer failure. Non-zero exit_code alone does not set `error` — the script is still treated as successful.

Single-task mode searches active jobs first, then falls back to `archive/`, then `zombie/`. This allows querying archived tasks by id after they are archived.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `name` and `id` both provided | `Error: provide only one of name or id` |
| `filter` combined with `name` or `id` | `Error: filter is for list mode; do not combine with name or id` |
| Task not found | `Error: no job named 'X' found in active, archive, or zombie` |
| No pid in meta (corrupted) | `Error: task '<X>' meta is corrupted (pid missing); investigate ~/.local/share/remote-mcp/jobpane/<sid>/<host>/<id>-meta.json manually` |
| Remote batched exec times out | `Error: ...` (full error with no partial results returned) |

## Remote ops

**List mode**: at most one batched exec regardless of job count — `echo "now=$(date +%s)"; for pid in ...; do kill -0 $pid 2>/dev/null && echo "$pid=A" || echo "$pid=D"; done`. Skipped entirely when all active jobs are in terminal state (zero remote ops).

**Single-task mode**: 0–4 remote ops depending on state and status script:

| Scenario | Remote ops |
|----------|-----------|
| Terminal state, no status script | 0 |
| Terminal state, status script (cache hit) | 2 (stat + exec) |
| Non-terminal state, no status script | 1 (kill -0) |
| Non-terminal state, status script (cache miss) | 4 (kill -0 + stat + upload + exec) |

## Routing

Jobs is in the `_with_retry` whitelist (writes only to local meta; no remote side effects that make retry unsafe).

## See also

- [Bash](./bash.md) — launch background tasks
- [JobKill](./job-kill.md) — send a kill signal
- [JobArchive](./job-archive.md) — archive finished tasks
- [JobScript](./job-script.md) — attach a status script
- Spec §7, §8
