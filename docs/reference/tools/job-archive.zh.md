# JobArchive

> English version: [job-archive.md](./job-archive.md)

归档已完成的后台任务——将其本地元数据移至 `archive/`（stopped/killed）或 `zombie/`（已放弃管理的 kill_failed）。纯本地操作，零远端调用。

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
    "as_zombie": {
      "type": "boolean",
      "default": false,
      "description": "仅对 kill_failed 任务有意义。设为 true 表示承认"我放弃 kill 了；进程仍在远端运行，但面板将其遗忘"。被归档的任务 zombie=true，并计入主机的 zombie 阈值统计。默认 false 仅归档 stopped/killed 任务（依据 meta 缓存的 state——如需更新请先调用 Jobs）。"
    }
  }
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `name` | string | 否 | — | 任务别名。与 `id` 互斥。`name` 与 `id` 二者必须提供其一。 |
| `id` | integer | 否 | — | 任务 id。与 `name` 互斥。 |
| `as_zombie` | boolean | 否 | `false` | 设为 `true` 以将 `kill_failed` 任务作为 zombie 归档（已放弃）。对其他状态拒绝。 |

## 状态要求

JobArchive 直接读取 `<id>-meta.json` 中**缓存的 state**，不发起任何远端观察。行为依据缓存的 state 分支：

| 缓存 state | `JobArchive(name=X)` | `JobArchive(name=X, as_zombie=True)` |
|---|---|---|
| `running` | Error：任务正在运行；先调 Jobs 刷新，读日志，再归档 | Error：as_zombie 要求 kill_failed |
| `stopped` | 接受——移至 `archive/` | Error：as_zombie 要求 kill_failed |
| `killed` | 接受——移至 `archive/` | Error：as_zombie 要求 kill_failed |
| `kill_failed` | Error：进程仍活；重试 JobKill 或使用 as_zombie=True | 接受——移至 `zombie/` |

**设计理由**：若缓存 state 为 `running`，说明 agent 尚未确认任务结束，也未查看其结果。未经查看就归档属于错误操作。应先调 `Jobs(name=X)` 刷新状态，读取日志，再归档。`stopped`/`killed` 的缓存状态始终可信（终态不重复观察；PID 复用不会让已停止的任务再次显示为 running）。

## 返回值

### 普通归档（stopped 或 killed）

```
Archived 'x86_python_build' (id=17).
  archived_at: 2026-05-31T23:00:00Z
  log_path: /home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log    (still readable)

This name is now free for reuse by new launches (which will get a new
id). The old task's meta has been moved to .../archive/17-meta.json
and remains queryable via Jobs(id=17).

[host=tjcs_ex_ln3 cwd=/home/user]
```

### Zombie 归档（kill_failed + as_zombie=True）

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

### Zombie 升级告警（zombie 数 ≥ 5，追加在返回末尾）

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

## 行为说明

- **零远端操作**：JobArchive 纯本地执行。不建立 SSH 通道。远端 pid 文件、status.sh 缓存及日志文件原样不动。
- **本地文件操作**：向 `<id>-meta.json` 写入 `archived_at`，再将其移至 `archive/` 或 `zombie/`。若本地存在 `<id>-status.sh`，一同移至目标目录。
- **名称复用**：归档后任务名称释放。同名的新启动任务获得新 id。旧任务的 meta 仍可通过 `Jobs(id=N)` 查询。
- **远端文件持久保留**：日志文件仍可读。pid 文件保留。status.sh 远端缓存保留（但面板不再引用）。这些文件在归档时不清理——有意设计，供事后分析使用。
- **陈旧 state 风险**：若缓存 state 不正确（例如明知任务已停止但 Jobs 未刷新），在调 `JobArchive` 前先调 `Jobs(name=X)` 更新缓存。这是正确的工作流程。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 任务未找到 | `Error: no job named 'X' found in active panel` |
| state 为 `running`，默认归档 | `Error: task 'X' is in state 'running' per panel (last observed at <ts>). Archive is for tasks you have processed the results of. ...` |
| state 为 `kill_failed`，默认归档 | `Error: cannot archive task 'X' in state 'kill_failed' (pid=<pid>, kill_attempts=N). Either: call JobKill(name='X') again to retry ..., or give up via JobArchive(name='X', as_zombie=True) ...` |
| `as_zombie=True` 但 state 不是 `kill_failed` | `Error: as_zombie=True requires state=kill_failed; this task is '<state>' — use plain JobArchive(name='X')` |
| 已归档 | `Error: task 'X' (id=N) is already archived` |

## 路由

JobArchive 在 `NO_RETRY_TOOLS` 中——本地文件移动不在 SSH 故障时重试（无 SSH 操作，但此分类可防止 call_tool 包装器因重试造成重复执行）。

## 相关

- [Jobs](./jobs.md) — 归档前刷新状态
- [JobKill](./job-kill.md) — 归档前发送 kill 信号
- [任务面板设计说明](../../explanation/job-panel.zh.md) — 归档语义的设计理由
- 规范 §11
