# JobKill

> English version: [job-kill.md](./job-kill.md)

向面板跟踪的后台任务发送 kill 信号，并在单次打包的远端 exec 中验证进程存活状态。

## Schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "任务名称。与 id 互斥。"
    },
    "id": {
      "type": "integer",
      "description": "任务 id。与 name 互斥。"
    },
    "kill_cmd": {
      "type": "string",
      "description": "可选。在远端执行的完整 shell 命令。默认：'kill -TERM -- -<pid>'（取 pid 负值以向整个进程组发信号；之所以有效是因为启动时使用了 setsid）。Slurm 场景：'scancel 12345'。SIGKILL 升级：'kill -KILL -- -<pid>'。运行时特定关闭：'kill -USR1 <pid>'。"
    }
  }
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `name` | string | 否 | — | 任务别名。与 `id` 互斥。`name` 与 `id` 二者必须提供其一。 |
| `id` | integer | 否 | — | 任务 id。与 `name` 互斥。 |
| `kill_cmd` | string | 否 | `kill -TERM -- -<pid>` | 在远端执行的 shell 命令。默认针对进程组（由启动时的 `setsid` 创建）。 |

## 返回值

### kill 成功（state 变为 `killed`）

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

### kill 失败（进程仍活——尝试次数 ≥ 3 时触发 L1 告警）

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

### L2 主机级别告警（本 host 有 ≥ 5 个 stuck 任务，追加在 L1 之后）

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

### kill 命令超时（5 秒）

```
Error: kill command did not respond within 5s on tjcs_ex_ln3.
kill_requested_at has been recorded; state was not updated this call.
Run Jobs(name='X') to refresh; if state becomes 'killed' the process
died after timeout; if state remains 'running' or 'kill_failed', the
kill command may have failed to take effect.

[host=tjcs_ex_ln3 cwd=/home/user]
```

## 行为说明

- **打包 exec**：JobKill 发出单次远端 exec，先执行 `kill_cmd`，等待 100 ms，再执行 `kill -0 <pid>` 验证存活状态——两次操作合并在一个 SSH 通道内完成。
- **kill_requested_at 先写**：远端 exec 之前先更新本地 meta 的 `kill_requested_at`。若 exec 成功但响应丢失，下次 `Jobs` 调用会看到非 null 的 `kill_requested_at` 并正确推导状态。
- **状态推导**：`kill -0` 失败 → state `killed`；`kill -0` 成功 → state `kill_failed`。写回本地 meta。
- **不自动 zombify**：JobKill 不会自动将任务移至 `zombie/`。这是 agent 通过 `JobArchive(as_zombie=True)` 主动决定的操作。
- **已归档任务**：对已归档任务调用 JobKill 返回 Error。
- **默认 kill 命令**：针对进程组（`kill -- -<pid>`），因为 `setsid` 使启动的 pid 等于 PGID。若使用了不含 `setsid` 的自定义启动器，进程组 kill 可能不适用。
- **`sleep 0.1`**：100 ms 暂停给 SIGTERM 传播到进程留出时间。使用自定义信号处理程序的进程可能需要更长时间；后续 `Jobs` 调用会获取最终状态。

## 升级阈值

| 常量 | 值 | 触发条件 |
|------|-----|---------|
| `KILL_FAIL_PER_TASK_THRESHOLD` | 3 | L1 告警（单任务） |
| `STUCK_KILL_WARN_THRESHOLD` | 5 | L2 告警（主机级别） |

## 路由

JobKill 在 `NO_RETRY_TOOLS` 中——SSH 故障触发重连，但 kill 命令**不**自动重发（非幂等副作用：kill 可能已执行）。

## 相关

- [Jobs](./jobs.md) — 观察状态并运行状态脚本
- [JobArchive](./job-archive.md) — 确认停止后归档，或放弃后 zombify
- [Bash](./bash.md) — 启动后台任务
- 规范 §10
