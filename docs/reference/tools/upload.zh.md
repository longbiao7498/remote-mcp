# Upload

> English version: [upload.md](./upload.md)

通过 SFTP 把本地文件推送到远程主机。二进制安全。

**Linux/macOS 用户优先用 `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** —— 非阻塞、不限大小、配合 `rsync` 可恢复。Upload 主要是为没有 `scp` 的 Windows 用户准备的兜底。

## Schema

```json
{
  "type": "object",
  "properties": {
    "local_path": {"type": "string"},
    "remote_path": {"type": "string"}
  },
  "required": ["local_path", "remote_path"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `local_path` | string | 是 | — | **本机**绝对路径或含 ~（通过 `os.path.expanduser` 展开）。**不受**已配置的远程 cwd 影响。 |
| `remote_path` | string | 是 | — | 远程绝对路径，或相对于已配置 cwd 的相对路径（与 Read/Write 等一致）。已存在则覆盖。父目录通过 SFTP `mkdir` 自动创建。 |

## 返回值

字符串。

**成功**：`Successfully uploaded <N> bytes from <local_path> to <remote_path>`，其中 `<N>` 是本地文件的字节数。

**失败**：见下面[错误措辞](#错误措辞)。

MCP 服务器会在每次输出（成功和错误）后追加 `\n\n[host=X cwd=Y]`。工具本身的输出是该后缀之前的所有内容。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `local_path` 不存在 | `Error: Local file not found: <local_path>` |
| `local_path` 是目录 | `Error: Local path is a directory, not a file: <local_path>` |
| 本地文件大小 > `conn.config.transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| 远程写入权限拒绝（`PermissionError` 或 `errno=EACCES` 的 `IOError`） | `Error: Permission denied: <remote_path>` |
| 其他 SFTP 失败 | `Error: <message>` |

## 行为说明

- 用 paramiko 的 `sftp.put(local, remote)`，流式传输——不会把整个文件读入内存。适合传输到 `transfer_size_cap` 上限以内的文件。
- `remote_path` 的父目录通过 SFTP `mkdir` 递归创建（与 Write 一致）。
- 本地文件按二进制方式读取，**不**假设 UTF-8。
- 传输期间阻塞——无进度上报。对大文件用 `Bash + scp` 后台模式更合适。
- `transfer_size_cap` 在传输开始前用 `os.path.getsize()` 检查；超限则不传任何字节。

## 带宽特征

- **传输大小**：等于本地文件字节数，受 SSH 压缩影响。
- **往返次数**：SFTP session 复用一份；父目录创建 1 个或多个 `mkdir` 往返；一次 SFTP `put`（内部多 packet 但是一次逻辑操作）。
- **阻塞对话**直到传输完成。对大文件用 `Bash("scp ...", run_in_background=true)`。

## 相关

- [Download](./download.zh.md) —— 反向
- [Write](./write.zh.md) —— 写文本字符串而不是本地文件路径
- [Bash](./bash.zh.md) —— 用于 `scp` + `run_in_background=true` 模式
- [操作指南：运行长时后台任务](../../how-to/run-long-background-jobs.zh.md)
- Spec —— *不在 spec 中；v0.1.1 新增*
