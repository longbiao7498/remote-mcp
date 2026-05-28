# Bash

> English version: [bash.md](./bash.md)

在远程主机上执行 shell 命令，可在持久前台会话中运行，也可作为独立的后台进程组运行。

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

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `command` | string | 是 | — | 在远程主机上执行的 shell 命令。原样传递给 bash——不做额外转义。 |
| `description` | string | 否 | `""` | 说明性标签。内部不使用；保留是为了与 Claude Code 原生 Bash 工具的 Schema 兼容。 |
| `timeout` | number | 否 | `120` | 前台超时秒数。`run_in_background=true` 时忽略。省略时使用 `conn.config.bash_timeout_default` 的值（默认 `120`）。 |
| `run_in_background` | boolean | 否 | `false` | 为 `true` 时，将命令作为独立的后台进程组启动并立即返回。 |

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

- `<name>` 是配置中的主机名（`conn.config.name` 的值）。
- `<cwd>` 是配置的远程 cwd——在所有调用中保持稳定。
- 输出中的 `\r\n` 序列归一化为 `\n`；裸 `\r` 字符被去除。
- 输出上限为 `conn.config.bash_output_cap` 字节（默认 100 KB）。截断时，输出以 `\n... [truncated to <N> bytes]` 结尾。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

### 后台输出（`run_in_background=true`）

后台进程启动后立即返回：

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

- `<pid>` 是 `setsid` 产生的 bash 的 PID。由于 `setsid` 会创建一个 PID = PGID 的新进程组，`kill -- -<pid>` 可杀死整个进程树。
- `<log_path>` 为 `/tmp/rmcp-bg-<12-hex-uuid>.log`。后台命令的 stdout 和 stderr 合并写入该文件。MCP 服务器退出时不清理该文件；重启后 `/tmp` 会被清空。
- 返回输出中的四行提示为字面字符串，格式如上所示。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 前台命令超时 | `Error: Command timed out after <timeout>s on <name>` |
| 后台启动未发出 `BG_PID=<n>` | `Error: failed to start background task on <name>. Output: <first 500 chars of output>` |

## 行为说明

- **非持久 shell**：每次调用都是全新的 `bash --noprofile --norc -c "..."`。`cd`、`export`、`source venv/bin/activate` 在调用之间**不会**保留——如需串联，请在同一行用 `&&` 连接。
- **快照重放**：远程 `~/.bashrc` 在 SSH 连接建立时加载一次；后续 Bash 调用会 `source` 保存的快照，恢复 PATH、别名、函数和导出的变量。连接建立后对 `~/.bashrc` 的修改在重连之前**不会**生效。
- **配置的 cwd**：每次 Bash 调用均从配置的 `cwd`（`--cwd /opt/app`，默认为 `$HOME`）开始。快照以 `cd <cwd> || exit 1` 结尾。
- **无 PTY**：stdin 为 `/dev/null`。`srun`、`cat`（无参数）等需要读取 stdin 的命令不会挂起。不支持交互式工具（`vim`、`top`、REPL）。
- **超时**：关闭 SSH 通道，向远程命令的会话发送 SIGHUP——终止该命令及其所有子进程。超时前收集到的部分 stdout 会包含在错误输出中。
- **后台（`run_in_background=true`）**：启动 `setsid nohup bash --noprofile --norc -c "source <snapshot>; ..." > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`。通过 source 快照使配置的 cwd 和 PATH 生效。返回 PID + 日志路径 + 4 条操作命令。使用 `kill -- -<pid>` 终止整个进程组。
- **输出**：stdout 与 stderr 合并输出。非零退出时末尾附加 `[Exit code: N]`。上限为 `bash_output_cap`（默认 100 KB）。统一的 `[host=X cwd=Y]` 前缀由 MCP 服务器追加，而非工具本身。

## 带宽特征

- **前台：** 输出字节通过网络传输一次。大量输出应在服务端通过 `head`/`tail` 过滤。100 KB 上限是安全防护，而非服务端过滤的替代方案。
- **后台：** 启动时仅 `BG_PID=<n>` 行通过网络传输。后续输出通过 [Read](./read.md) 轮询日志文件——每次轮询仅通过 `offset` 传输所请求的新行。
- **往返次数：** 前台 = 每次调用一次逻辑往返（单次 exec_command + 通道读取）；后台启动 = 一次往返；后续轮询 = 每次通过 Read 一次往返。

## 相关

- [Read](./read.md) — 轮询后台任务日志文件输出
- [FileStat](./file-stat.md) — 读取前检查日志文件大小
- [Glob](./glob.md) — 无需运行 shell find 命令即可查找文件
- [Grep](./grep.md) — 在服务端搜索文件内容
- Spec §5.3.7
