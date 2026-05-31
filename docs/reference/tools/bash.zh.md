# Bash

> English version: [bash.md](./bash.md)

在远程主机上执行 shell 命令，可作为阻塞式前台调用运行，也可作为带面板跟踪的独立后台进程运行。

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
      "description": "仅后台模式。stdout+stderr 的绝对远端路径。默认为 ~/.cache/remote-mcp-<sid>-<id>.log。父目录自动创建。"
    },
    "name": {
      "type": "string",
      "description": "仅后台模式。供面板引用的任务别名。默认为 bg-<uuid12>。在活跃任务中必须唯一。格式：[A-Za-z0-9_.-]+ 长度 1-64。"
    }
  },
  "required": ["command"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `command` | string | 是 | — | 在远程主机上执行的 shell 命令。原样传递给 bash——不做额外转义。 |
| `description` | string | 否 | `""` | 简短描述（CC 原生兼容字段）。`run_in_background=true` 时，同时作为任务描述持久化到面板（超过 500 字符时截断）。 |
| `timeout` | number | 否 | `120` | 前台超时秒数。`run_in_background=true` 时忽略。 |
| `run_in_background` | boolean | 否 | `false` | 为 `true` 时，作为面板跟踪的后台任务启动并立即返回。 |
| `log_path` | string | 否 | `~/.cache/remote-mcp-<sid>-<id>.log` | 仅后台模式。显式指定的远端日志路径。父目录通过 `mkdir -p` 自动创建。若父路径处已存在非目录文件，返回 Error。 |
| `name` | string | 否 | `bg-<uuid12>` | 仅后台模式。人类可读的任务名称。与活跃（未归档）任务冲突返回 Error。 |

## 返回值

返回字符串。格式取决于 `run_in_background`。

### 前台输出（`run_in_background=false`）

**成功时（退出码为 0）：**

```
<command output>

[host=<name> cwd=<cwd>]
```

**成功时（退出码非零）：**

```
<command output>
[Exit code: <N>]

[host=<name> cwd=<cwd>]
```

- `<name>` 是配置中的主机名。
- `<cwd>` 是配置的远程 cwd——在所有调用中保持稳定。
- `\r\n` 序列归一化为 `\n`；裸 `\r` 字符被去除。
- 输出上限为 `bash_output_cap`（默认 100 KB）；截断时以 `\n... [truncated to <N> bytes]` 结尾。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

### 后台输出（`run_in_background=true`）

远端进程 PID 确认后立即返回（详见[同步 PID 确认](#同步-pid-确认)）：

```
Started background task.
  id: 17
  name: x86_python_build
  log_path: /home/user/.cache/remote-mcp-a1b2c3d4e5f6-17.log
  pid: 1259443
  started_at: 2026-05-31T08:40:53Z

[host=<name> cwd=<cwd>]
```

字段说明：
- `id` — 当前 session + host 范围内单调递增整数。用于 `Jobs(id=N)`、`JobKill(id=N)`、`JobArchive(id=N)`。
- `name` — 传入的别名，或自动生成的 `bg-<uuid12>`。
- `log_path` — 远端合并日志（stdout+stderr）的绝对路径。
- `pid` — `setsid` 产生的进程组组长的 PID。`kill -- -<pid>` 可终止整个进程树。
- `started_at` — 远端 shell 的 ISO-8601 UTC 时间戳。

### 同步 PID 确认

工具在确认远端 PID 之前不会返回。若 exec 响应丢失（网络故障）：

1. 工具立即回退到 SFTP 读取 `~/.cache/remote-mcp-<sid>-<id>-pid`。
2. 若文件存在且内容为合法整数，启动成功（附带 NOTE 说明 `started_at` 由 pid 文件 mtime 近似推算）。
3. 若两者均失败，任务**不**进入面板，返回 Error 并附回收指引。本地预写的面板条目立即清理。

此机制保证每条面板条目都对应一个已确认存在的远端进程。详见规范 §5.3.4。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 前台命令超时 | `Error: Command timed out after <timeout>s on <name>` |
| `name` 不符合 `^[A-Za-z0-9_.-]{1,64}$` | `Error: invalid job name 'X': must match ^[A-Za-z0-9_.-]{1,64}$` |
| `name` 与活跃面板任务冲突 | `Error: job name 'X' already in active panel; archive the old one with JobArchive(name='X') or pick a different name` |
| `log_path` 父路径存在但非目录 | `Error: log_path parent ... exists but is not a directory; cannot mkdir -p` |
| 后台 PID 无法确认（exec 丢失 + SFTP 兜底失败） | `Error: background launch for '<name>' (id=<id>) on <host> could not be confirmed. ...`（附回收步骤） |

## 行为说明

- **非持久 shell**：每次调用都是全新的 `bash --noprofile --norc -c "..."`。`cd`、`export`、`source venv/bin/activate` 在调用之间**不会**保留——如需串联，请在同一行用 `&&` 连接。
- **前台 shell wrap**：`bash --noprofile --norc -c 'source <snapshot_path> 2>/dev/null || true; <user_command>' </dev/null`。快照提供 PATH、别名、函数及 `cd <cwd>`。
- **后台 shell wrap**：`( setsid nohup bash --noprofile --norc -c 'source <snapshot_path> 2>/dev/null || true; <user_command>' > <log_path> 2>&1 </dev/null & PID=$!; echo $PID > ~/.cache/remote-mcp-<sid>-<id>-pid; ... echo "BG_PID=$PID" ... )`。`setsid` 创建新 session——后台进程在 SSH 通道关闭、笔记本休眠及 MCP 服务重启后均能存活。
- **快照重放**：远程 `~/.bashrc` 在 SSH 连接建立时加载一次。后续调用 source 已捕获的快照。连接建立后对 `~/.bashrc` 的修改在重连之前不会生效。
- **配置的 cwd**：每次调用均从配置的 `cwd` 开始。快照以 `cd <cwd> || exit 1` 结尾。
- **无 PTY**：stdin 为 `/dev/null`。`srun`、`cat`（无参数）等读 stdin 的命令不会挂起。不支持交互式工具（`vim`、`top`、REPL）。
- **超时（前台）**：关闭 SSH 通道，向远程命令的会话发送 SIGHUP。部分 stdout 会包含在错误输出中。
- **后台日志**：stdout 与 stderr 合并写入 `log_path`。MCP 服务退出时**不**清理该文件（`~/.cache` 是持久存储）。
- **输出**：stdout 与 stderr 合并输出。非零退出时末尾附加 `[Exit code: N]`。上限为 `bash_output_cap`（默认 100 KB）。

## 后台任务管理工作流

```
# 启动
Bash(run_in_background=True, name="build", command="bash ~/build.sh > ~/build.log 2>&1")
# → id: 3, pid: 12345, log_path: /home/user/.cache/remote-mcp-abc-3.log

# 查询状态（从远端刷新面板状态）
Jobs(name="build")

# 增量读取日志
Read("/home/user/.cache/remote-mcp-abc-3.log", offset=50)

# Kill
JobKill(name="build")

# 确认已停止并查看结果后归档
JobArchive(name="build")
```

## 带宽特征

- **前台：** 每次调用一次 exec 往返。输出字节通过网络传输一次；大量输出应在服务端通过 `head`/`tail` 过滤。
- **后台启动：** 两次 exec 往返（一次 `mkdir -p`，一次 wrap），仅在 exec 响应丢失时才有额外 SFTP 读取。
- **后台轮询：** 每次 `Jobs` 列表调用至多一次批量 exec，无论任务数量；每次 `Jobs(name=X)` 单任务调用 1–4 次远端操作，取决于状态与是否挂载状态脚本。

## 相关

- [Jobs](./jobs.md) — 列出和查询面板任务
- [JobKill](./job-kill.md) — 向面板任务发送 kill 信号
- [JobArchive](./job-archive.md) — 归档已完成的面板任务
- [JobScript](./job-script.md) — 为面板任务挂载状态脚本
- [Read](./read.md) — 轮询后台任务日志文件输出
- [FileStat](./file-stat.md) — 读取前检查日志文件大小
- 规范 §5
