# JobArchive

> 中文版本：[job-archive.zh.md](./job-archive.zh.md)

Archive a finished background job — move its local metadata to `archive/` (stopped/killed) or `zombie/` (given-up kill_failed). Purely local: zero remote ops.

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
    "as_zombie": {
      "type": "boolean",
      "default": false,
      "description": "Only meaningful when archiving a kill_failed task. Setting true acknowledges 'I give up trying to kill this; the process keeps running on remote but the panel forgets it'. The archived task gets zombie=true and counts toward the host's zombie threshold. Default false archives only stopped/killed tasks (per cached state in meta — refresh via Jobs first if needed)."
    }
  }
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | no | — | Job alias. Mutually exclusive with `id`. One of `name` or `id` required. |
| `id` | integer | no | — | Job id. Mutually exclusive with `name`. |
| `as_zombie` | boolean | no | `false` | Set `true` to archive a `kill_failed` task as a zombie (gave-up). Rejected for other states. |

## State requirements

JobArchive reads the **cached state from `<id>-meta.json`** without issuing any remote observation. The behavior depends on the cached state:

| Cached state | `JobArchive(name=X)` | `JobArchive(name=X, as_zombie=True)` |
|---|---|---|
| `running` | Error: task is running; call Jobs to refresh, read log, then archive | Error: as_zombie requires kill_failed |
| `stopped` | Accepted — moved to `archive/` | Error: as_zombie requires kill_failed |
| `killed` | Accepted — moved to `archive/` | Error: as_zombie requires kill_failed |
| `kill_failed` | Error: process still alive; retry JobKill or use as_zombie=True | Accepted — moved to `zombie/` |

**Why this design**: if the cached state is `running`, the agent hasn't confirmed the task finished and hasn't reviewed its results. Archiving without review is the wrong action. Call `Jobs(name=X)` first to refresh state, then read the log, then archive. The cached state for `stopped`/`killed` is always trustworthy (terminal states are not re-observed; PID reuse cannot make a stopped task appear running again).

## Returns

### Normal archive (stopped or killed)

```
Archived 'x86_python_build' (id=17).
  archived_at: 2026-05-31T23:00:00Z
  log_path: /home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log    (still readable)

This name is now free for reuse by new launches (which will get a new
id). The old task's meta has been moved to .../archive/17-meta.json
and remains queryable via Jobs(id=17).

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Zombie archive (kill_failed + as_zombie=True)

```
Archived 'x86_python_build' (id=17) as ZOMBIE.
  archived_at: 2026-05-31T23:00:00Z
  kill_attempts: 4 (see Jobs(id=17) for details)
  log_path: /home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log    (still readable)

The process may still be running on tjcs_ex_ln3 outside panel management.
Investigate manually via Bash if its results matter.

Zombie count on tjcs_ex_ln3 is now 5.

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Zombie escalation warning (zombie count ≥ 5, appended)

```
==================================================================
ESCALATION WARNING: zombie count on <host> is now 5 (>= threshold).
==================================================================

Possible causes (review BEFORE assuming remote server is broken):

1. Recent zombie tasks may share a root cause — inspect their
   attempt histories with Jobs(filter='zombies') and Jobs(id=N) for
   each. If they all failed the same kill command, the issue may be
   in your kill_cmd choice (e.g. wrong PID, missing setsid, wrong
   signal for the runtime).
2. If kill_cmd exit codes were all 0 but processes still alive, the
   remote process is genuinely refusing to die — possibly stuck in
   uninterruptible IO (D state), kernel bug, or sudoed root process
   you can't signal as your user.
3. Only after ruling out the above: remote server may be unhealthy.

RECOMMENDED: stop the current task loop and SSH into <host> manually
to investigate. Continued operation may produce more zombies.
```

## Behavior notes

- **Zero remote ops**: JobArchive is purely local. No SSH channel is opened. Remote pid file, status.sh cache, and log file are left in place unchanged.
- **Local file operations**: rewrites `<id>-meta.json` with `archived_at`, then moves it to `archive/` or `zombie/`. If `<id>-status.sh` exists locally, it is moved to the same destination directory.
- **Name reuse**: after archiving, the job name is released. A new launch with the same name gets a new id. The old meta is still queryable via `Jobs(id=N)`.
- **Remote files persist**: log file remains readable. Pid file remains. Status.sh remote cache remains (but is no longer referenced by the panel). These files are not cleaned up on archive — deliberate, for post-mortem access.
- **Stale state risk**: if the cached state is wrong (e.g., you know the task stopped but Jobs hasn't been called to refresh), call `Jobs(name=X)` before `JobArchive` to update the cache. This is the correct workflow.

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| Task not found | `Error: no job named 'X' found in active panel` |
| State is `running`, default archive | `Error: task 'X' is in state 'running' per panel (last observed at <ts>). Archive is for tasks you have processed the results of. ...` |
| State is `kill_failed`, default archive | `Error: cannot archive task 'X' in state 'kill_failed' (pid=<pid>, kill_attempts=N). Either: call JobKill(name='X') again to retry ..., or give up via JobArchive(name='X', as_zombie=True) ...` |
| `as_zombie=True` but state is not `kill_failed` | `Error: as_zombie=True requires state=kill_failed; this task is '<state>' — use plain JobArchive(name='X')` |
| Already archived | `Error: task 'X' (id=N) is already archived` |

## Routing

JobArchive is in `NO_RETRY_TOOLS` — local file moves are not retried on SSH failure (there is no SSH involved, but the classification prevents double-execution if the call_tool wrapper ever retries).

## See also

- [Jobs](./jobs.md) — refresh state before archiving
- [JobKill](./job-kill.md) — send kill signal before archiving
- [job-panel explanation](../../explanation/job-panel.md) — archive semantics rationale
- Spec §11
