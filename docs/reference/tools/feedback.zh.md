# Feedback

> English version: [feedback.md](./feedback.md)

将关于 remote-mcp 工具本身的 bug 报告或改进建议追加到本地 JSONL 文件中。

## Schema

```json
{
  "type": "object",
  "properties": {
    "category": {
      "type": "string",
      "enum": ["bug", "enhancement"]
    },
    "summary": {"type": "string"},
    "details": {"type": "string", "default": ""}
  },
  "required": ["category", "summary"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `category` | string | 是 | — | 必须为 `"bug"` 或 `"enhancement"`。 |
| `summary` | string | 是 | — | 单行描述。去除空白后必须非空。 |
| `details` | string | 否 | `""` | 可选的详细说明。去除首尾空白后按原样存储；若为空则 JSON 条目中为 `null`。 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：**

```
Feedback recorded: [<category>] <summary> -> <feedback_path>
```

`<feedback_path>` 是 JSONL 文件的本地文件系统路径，由配置决定（默认 `~/.local/share/remote-mcp/feedback.jsonl`）。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。错误时不会写入文件。

MCP 服务器会在每次输出（成功和错误）后追加 `\n\n[host=X cwd=Y]`。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `category` 不是 `"bug"` 或 `"enhancement"` | `Error: category must be 'bug' or 'enhancement', got '<value>'` |
| `summary` 为空或仅含空白字符 | `Error: summary cannot be empty` |

## 行为说明

### 适用范围

Feedback 是关于 remote-mcp 工具本身的——包括其 Schema、错误消息、输出格式或缺失的功能。它不是用于记录用户代码或远程系统 bug 的渠道。

### JSONL 条目结构

每次成功调用向文件追加恰好一行。该行是具有以下字段的 JSON 对象：

| 字段 | 类型 | 来源 | 描述 |
|------|------|------|------|
| `ts` | string | 自动 | UTC ISO 8601，秒精度（如 `"2026-05-26T10:00:00+00:00"`） |
| `host` | string | 自动 | `conn.config.name` — 当前 MCP 服务器实例所连接的远程主机 |
| `category` | string | 调用方 | `"bug"` 或 `"enhancement"` |
| `summary` | string | 调用方 | `summary` 参数去除空白后的值 |
| `details` | string or null | 调用方 | `details` 去除空白后的值，若 `details` 为空则为 `null` |
| `session_pid` | integer | 自动 | 本地 MCP 服务器进程的 PID |

示例条目（文件中的一行）：

```json
{"ts": "2026-05-26T10:00:00+00:00", "host": "gpu-box", "category": "bug", "summary": "Glob missed nested matches", "details": "Pattern src/**/*.py returned no results for src/a/b/c.py", "session_pid": 12345}
```

### 仅写本地

文件仅写入本地机器。不向远程主机或外部服务传输任何内容。接受 `conn` 参数仅为了读取 `conn.config.name` 以填写 `host` 字段。

### 并发安全性

多个每主机 MCP 服务器进程可能同时向同一 JSONL 文件追加内容。每次调用发起单次 `write()`，写入一行 JSONL。在 POSIX 系统上，向以 `O_APPEND` 打开的文件写入少于 `PIPE_BUF` 字节（Linux 上通常为 4 KB）的数据是原子操作。单条 feedback 条目远低于此限制。无需加锁。

### 文件位置

路径取自配置（默认 `~/.local/share/remote-mcp/feedback.jsonl`）。若父目录不存在，则自动创建（相当于 `mkdir -p`）。文件不会自动轮转或截断。

## 带宽特征

- 无网络活动。所有 I/O 均为本地文件系统操作。
- 正常情况下调用在 1 毫秒内完成。

## 相关

- [Bash](./bash.md) — 对远程系统进行操作
- Spec §5.3.10
