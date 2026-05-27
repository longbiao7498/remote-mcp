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
[host=<name> cwd=<cwd>]
<command output>
```

**成功时（退出码非零）：**

```
[host=<name> cwd=<cwd>]
<command output>
[Exit code: <N>]
```

- `<name>` 是配置中的主机名（`conn.config.name` 的值）。
- `<cwd>` 是命令执行完成后的工作目录，从哨兵行中获取。
- 输出中的 `\r\n` 序列归一化为 `\n`；裸 `\r` 字符被去除。
- 输出上限为 `conn.config.bash_output_cap` 字节（默认 100 KB）。截断时，输出以 `\n... [truncated to <N> bytes]` 结尾。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

### 后台输出（`run_in_background=true`）

后台进程启动后立即返回：

```
[host=<name> cwd=<cwd>]
Started background task.
  PID: <pid>
  Log: <log_path>

To check status:    Bash("kill -0 <pid> && echo running || echo done")
To read new output: Read("<log_path>", offset=<last_line+1>)
To stop gracefully: Bash("kill -TERM -- -<pid>")
To force stop:      Bash("kill -KILL -- -<pid>")
```

- `<pid>` 是 `setsid` 产生的 bash 的 PID。由于 `setsid` 会创建一个 PID = PGID 的新进程组，`kill -- -<pid>` 可杀死整个进程树。
- `<log_path>` 为 `/tmp/rmcp-bg-<12-hex-uuid>.log`。后台命令的 stdout 和 stderr 合并写入该文件。MCP 服务器退出时不清理该文件；重启后 `/tmp` 会被清空。
- 返回输出中的四行提示为字面字符串，格式如上所示。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 前台命令超时 | `Error: Command timed out after <timeout>s on <name>` |
| 后台启动包装器超时（10 秒内部限制） | `Error: failed to launch background task on <name> (timeout)` |
| 后台启动未发出 `BG_PID=<n>` | `Error: failed to start background task on <name>. Output: <first 500 chars of output>` |

## 行为说明

- **持久会话。** 前台调用在 SSH 连接的生命周期内共享单个长期存活的 bash 进程。Shell 状态（当前目录、导出的变量、shell 函数）在各次前台调用之间持久保存。后台调用也通过该会话启动包装器，但后台进程本身是独立的。
- **后台进程隔离。** 后台命令包装为 `setsid nohup bash -c <cmd> > <log> 2>&1 </dev/null &`。`setsid` 创建新会话，使产生的 bash 成为进程组组长（PID = PGID）。由于持久会话以 `set +m`（禁用作业控制）运行，普通的 `&` 不会创建新进程组；需要 `setsid` 才能使 `kill -- -<pid>` 正确工作。
- **超时行为（前台）。** 超时时，工具向远程 bash 发送 Ctrl-C（`\x03`），然后返回错误字符串。bash 会话本身保持存活，供后续调用使用。
- **输出上限（前台）。** 上限在 `\r\n` 归一化之后应用。`[Exit code: N]` 后缀（如有）在上限检查之前追加。
- **不支持交互式命令。** 需要 PTY 的命令（`vim`、`top`、REPL、带密码提示的 `sudo`）无法工作。bash 会话设有 `TERM=dumb` 且无 PTY。
- **`description` 参数。** 被接受但忽略。其存在是为了让为 Claude Code 原生 Bash 编写的工具调用无需修改即可使用。
- **SSH 重连。** 若 SSH 连接在会话中途重建，shell 状态（cwd、env）将被重置。`server.py` 中的调用方会在下一次工具结果前追加一个 `[WARNING]` 描述重连情况。具体警告文本见 [CLAUDE.md](../../../CLAUDE.md)。

## 带宽特征

- **前台：** 输出字节通过网络传输一次。大量输出应在服务端通过 `head`/`tail` 过滤。100 KB 上限是安全防护，而非服务端过滤的替代方案。
- **后台：** 启动时仅 `BG_PID=<n>` 行通过网络传输。后续输出通过 [Read](./read.md) 轮询日志文件——每次轮询仅通过 `offset` 传输所请求的新行。
- **往返次数：** 前台 = 每次调用一次逻辑往返（基于哨兵）；后台启动 = 一次往返；后续轮询 = 每次通过 Read 一次往返。

## 相关

- [Read](./read.md) — 轮询后台任务日志文件输出
- [FileStat](./file-stat.md) — 读取前检查日志文件大小
- [Glob](./glob.md) — 无需运行 shell find 命令即可查找文件
- [Grep](./grep.md) — 在服务端搜索文件内容
- Spec §5.3.7
