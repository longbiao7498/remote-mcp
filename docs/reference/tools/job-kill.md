# JobKill

> 中文版本：[job-kill.zh.md](./job-kill.zh.md)

Send a kill signal to a panel-tracked background job and verify its liveness in a single packed remote exec.

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
    "kill_cmd": {
      "type": "string",
      "description": "Optional. Full shell command to run on the remote to kill the task. Default: 'kill -TERM -- -<pid>' (negates pid to signal the whole process group; works because Bash launch uses setsid). For Slurm: 'scancel 12345'. For SIGKILL escalation: 'kill -KILL -- -<pid>'. For runtime-specific shutdown: 'kill -USR1 <pid>'."
    }
  }
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | no | — | Job alias. Mutually exclusive with `id`. One of `name` or `id` is required. |
| `id` | integer | no | — | Job id. Mutually exclusive with `name`. |
| `kill_cmd` | string | no | `kill -TERM -- -<pid>` | Shell command to execute on the remote. The default targets the process group (created by `setsid` at launch). |

## Returns

### Successful kill (state becomes `killed`)

```
Kill requested for 'x86_python_build' (id=17).
  kill_command: kill -TERM -- -1259443
  command_exit_code: 0
  kill_requested_at: 2026-05-31T22:14:30Z
  kill_attempts_count: 1
  state_now: killed

Verify with Jobs(name="x86_python_build") — state is already 'killed' in
meta. If state stays 'kill_failed' after multiple retries, consider
JobArchive(name='X', as_zombie=True) to give up.

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Kill failed (process still alive — L1 warning at ≥ 3 attempts)

```
Kill requested for 'x86_python_build' (id=17).
  kill_command: kill -TERM -- -1259443
  command_exit_code: 0
  kill_requested_at: 2026-05-31T22:14:30Z
  kill_attempts_count: 3
  state_now: kill_failed

NOTE: this task has 3 failed kill attempts now. If the process resists
further signals, try `kill -KILL -- -<pid>`, `scancel --signal=KILL`,
or runtime-specific shutdown commands. After exhausting retries, give
up via JobArchive(name='X', as_zombie=True) to move it to the zombie
queue (it will keep running on remote unmanaged).

[host=tjcs_ex_ln3 cwd=/home/user]
```

### L2 host-level warning (≥ 5 stuck tasks on this host, appended after L1)

```
==================================================================
WARNING: <host> has 5 jobs with persistent kill failures.
==================================================================

These are tasks where the panel issued kill but the process keeps
running. Pattern of failure across multiple tasks suggests:
  - your kill_cmd choices may be inappropriate (wrong signal / wrong
    PID / missing setsid in launch); inspect kill_attempts arrays
    via Jobs(name=...) to compare what you tried
  - or the remote host may have signal-resistant processes (D-state
    IO, kernel issues, sudoed root)

Consider pausing automation and investigating before more launches.
List affected tasks: Jobs(filter='stuck_kill').

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Kill command timed out (5 s)

```
Error: kill command did not respond within 5s on tjcs_ex_ln3.
kill_requested_at has been recorded; state was not updated this call.
Run Jobs(name='X') to refresh; if state becomes 'killed' the process
died after timeout; if state remains 'running' or 'kill_failed', the
kill command may have failed to take effect.

[host=tjcs_ex_ln3 cwd=/home/user]
```

## Behavior notes

- **Packed exec**: JobKill issues a single remote exec that runs `kill_cmd`, waits 100 ms, then runs `kill -0 <pid>` to check liveness — two operations in one SSH channel.
- **kill_requested_at written first**: the local meta is updated with `kill_requested_at` before the remote exec. If the exec succeeds but response is lost, the next `Jobs` call will see the non-null `kill_requested_at` and derive state correctly.
- **State derivation**: `kill -0` fails → state `killed`; `kill -0` succeeds → state `kill_failed`. Written to local meta.
- **No auto-zombify**: JobKill never automatically moves a task to `zombie/`. That is the agent's deliberate decision via `JobArchive(as_zombie=True)`.
- **Archived tasks**: calling JobKill on an archived task returns Error.
- **Default kill command**: targets the process group (`kill -- -<pid>`) because `setsid` makes the launched pid equal to the PGID. If you used a custom launcher that does not use `setsid`, the group kill may not be appropriate.
- **`sleep 0.1`**: the 100 ms pause gives SIGTERM time to propagate to the process before the liveness check. Processes with custom signal handlers may take longer; a subsequent `Jobs` call will pick up the final state.

## Escalation thresholds

| Constant | Value | Trigger |
|----------|-------|---------|
| `KILL_FAIL_PER_TASK_THRESHOLD` | 3 | L1 warning (per-task) |
| `STUCK_KILL_WARN_THRESHOLD` | 5 | L2 warning (per-host) |

## Routing

JobKill is in `NO_RETRY_TOOLS` — SSH failure triggers reconnect but the kill command is NOT re-issued automatically (non-idempotent side effect: the kill may have run).

## See also

- [Jobs](./jobs.md) — observe state and run status scripts
- [JobArchive](./job-archive.md) — archive after confirmed stop, or zombify after giving up
- [Bash](./bash.md) — launch background tasks
- Spec §10
