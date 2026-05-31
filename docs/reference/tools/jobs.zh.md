# Jobs

> English version: [jobs.md](./jobs.md)

查询后台任务面板：列出活跃任务的实时状态，或对单个任务进行详细检索。

## Schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "要查询的任务名称（单任务模式）。与 id 互斥。"
    },
    "id": {
      "type": "integer",
      "description": "要查询的任务 id（单任务模式）。与 name 互斥。"
    },
    "filter": {
      "type": "string",
      "enum": ["stopped_unprocessed", "stuck_kill", "zombies"],
      "description": "列表模式过滤器。stopped_unprocessed：state ∈ {stopped, killed} 且未归档（已结束待处理的任务）。stuck_kill：state == kill_failed 且 kill_attempts ≥ 3 且未归档。zombies：已归档为 zombie=true 的任务。"
    }
  }
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `name` | string | 否 | — | 任务别名。触发单任务模式。与 `id` 互斥。 |
| `id` | integer | 否 | — | 任务 id。触发单任务模式。与 `name` 互斥。 |
| `filter` | string | 否 | — | 列表模式过滤器。不可与 `name` 或 `id` 同时使用。 |

所有参数均为可选。无参数调用 `Jobs()` 时列出所有活跃（未归档）任务。

## 状态机

每次 Jobs 调用时实时推导任务真实状态：

| 状态 | 推导条件 |
|------|---------|
| `running` | `kill -0 <pid>` 成功，且 `kill_requested_at` 为 null |
| `stopped` | `kill -0 <pid>` 失败，且 `kill_requested_at` 为 null |
| `killed` | `kill -0 <pid>` 失败，且 `kill_requested_at` 非 null |
| `kill_failed` | `kill -0 <pid>` 成功，且 `kill_requested_at` 非 null（kill 已发送但进程仍活） |

**终态**：`stopped` 与 `killed` 为终态——一旦观察并缓存，后续 Jobs 调用不再对这些任务发起 `kill -0`（无需重复观察）。此优化避免原进程退出后 PID 被复用导致的误判。

**状态缓存**：Jobs 每次观察后将推导出的状态写回本地 `<id>-meta.json`。`JobArchive` 直接读取此缓存（无远端操作）。

## 过滤器值

| 过滤器 | 语义 |
|--------|------|
| _（无）_ | 所有活跃（未归档）任务 |
| `stopped_unprocessed` | state ∈ {stopped, killed}，未归档——已结束的任务；读取日志后归档 |
| `stuck_kill` | state == kill_failed 且 kill_attempts ≥ 3，未归档——抗 kill 任务；升级到 `kill -KILL` 或 `JobArchive(as_zombie=True)` |
| `zombies` | 已归档为 `zombie=true` 的任务——已放弃管理；远端进程可能仍在运行 |

## 返回值

### 列表模式

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

字段说明：

| 字段 | 说明 |
|------|------|
| `id` | 面板 id；用于 `Jobs(id=N)`、`JobKill(id=N)`、`JobArchive(id=N)` |
| `name` | 任务别名 |
| `description` | 启动时传入的描述 |
| `host` | 远端主机名 |
| `pid` | 远端进程 PID（进程组组长；`kill -- -<pid>` 可终止整个进程树） |
| `log_path` | 远端合并日志（stdout+stderr）；传给 `Read` 读取 |
| `state` | 本次调用刚刚观察的状态（见上方状态机） |
| `started_at` | ISO-8601 UTC 启动时间 |
| `elapsed_sec` | `远端当前时间 - started_at_unix`。对 stopped/killed 任务，此值包含任务停止后的等待时间 |
| `kill_requested_at` | 最近一次 kill 尝试的时间戳；null 表示从未 kill |
| `kill_attempts_count` | kill 尝试总次数；≥ 3 且 state 为 kill_failed 即为 stuck |
| `zombie` | 仅 `filter=zombies` 时为 true |

### 单任务模式

单任务模式额外包含以下字段，并在挂载状态脚本时运行该脚本：

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

较列表模式增加的字段：

| 字段 | 说明 |
|------|------|
| `command` | 启动时传入的原始命令字符串 |
| `kill_attempts` | 完整的 kill 尝试列表，每条含 `{at, at_unix, kill_cmd, exit_code, stdout, stderr}` |
| `archived_at` | 通过 id 查询已归档任务时非 null |
| `status_script_output` | 未挂载脚本时为 null；否则含 stdout/stderr/exit_code/elapsed_sec/error |

`status_script_output.error` 在脚本超时或 SSH 层故障时设置。单独的非零 exit_code 不设置 `error`——脚本仍被视为已成功运行。

单任务模式优先搜索活跃任务，其次回退到 `archive/`，再次到 `zombie/`。支持通过 id 查询已归档任务。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `name` 和 `id` 同时提供 | `Error: provide only one of name or id` |
| `filter` 与 `name` 或 `id` 同时使用 | `Error: filter is for list mode; do not combine with name or id` |
| 任务未找到 | `Error: no job named 'X' found in active, archive, or zombie` |
| meta 中 pid 缺失（数据损坏） | `Error: task '<X>' meta is corrupted (pid missing); investigate ~/.local/share/remote-mcp/jobpane/<sid>/<host>/<id>-meta.json manually` |
| 远端批量 exec 超时 | `Error: ...`（返回完整错误，不返回部分结果） |

## 远端操作数

**列表模式**：无论任务数量，至多一次批量 exec——`echo "now=$(date +%s)"; for pid in ...; do kill -0 $pid 2>/dev/null && echo "$pid=A" || echo "$pid=D"; done`。当所有活跃任务均为终态时完全跳过（零远端操作）。

**单任务模式**：0–4 次远端操作，取决于状态与是否挂载状态脚本：

| 场景 | 远端操作数 |
|------|-----------|
| 终态 + 无状态脚本 | 0 |
| 终态 + 有状态脚本（缓存命中） | 2（stat + exec） |
| 非终态 + 无状态脚本 | 1（kill -0） |
| 非终态 + 有状态脚本（缓存缺失） | 4（kill -0 + stat + 上传 + exec） |

## 路由

Jobs 保留在 `_with_retry` 白名单中（仅写入本地 meta，无远端副作用，重试安全）。

## 相关

- [Bash](./bash.md) — 启动后台任务
- [JobKill](./job-kill.md) — 发送 kill 信号
- [JobArchive](./job-archive.md) — 归档已完成的任务
- [JobScript](./job-script.md) — 挂载状态脚本
- 规范 §7、§8
