# Download

> English version: [download.md](./download.md)

通过 SFTP 把远程文件拉到本机。二进制安全。

**Linux/macOS 用户优先用 `Bash("scp <user>@<host>:<remote> <local>", run_in_background=true)`** —— 非阻塞、不限大小、配合 `rsync` 可恢复。Download 主要是为没有 `scp` 的 Windows 用户准备的兜底。

## Schema

```json
{
  "type": "object",
  "properties": {
    "remote_path": {"type": "string"},
    "local_path": {"type": "string"}
  },
  "required": ["remote_path", "local_path"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `remote_path` | string | 是 | — | 远程绝对路径，或相对于已配置 cwd 的相对路径（与 Read/Write 等一致）。 |
| `local_path` | string | 是 | — | **本机**绝对路径或含 ~（通过 `os.path.expanduser` 展开）。**不受**已配置的远程 cwd 影响。父目录必须已存在（不自动创建）。已存在则覆盖。 |

## 返回值

字符串。

**成功**：`Successfully downloaded <N> bytes from <remote_path> to <local_path>`，其中 `<N>` 是远程文件字节数。

**失败**：见下面[错误措辞](#错误措辞)。

MCP 服务器会在每次输出（成功和错误）后追加 `\n\n[host=X cwd=Y]`。工具本身的输出是该后缀之前的所有内容。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 本地父目录不存在 | `Error: Local parent directory not found: <dir>` |
| `remote_path` 不存在（SFTP `stat` 抛 `IOError`） | `Error: Remote file not found: <remote_path>` |
| `remote_path` 是目录 | `Error: Remote path is a directory, not a file: <remote_path>` |
| 远程文件大小 > `conn.config.transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| 本地写入权限拒绝（`PermissionError` 或 `errno=EACCES` 的 `IOError`） | `Error: Permission denied: <local_path>` |
| 其他 SFTP 失败 | `Error: <message>` |

## 行为说明

- 用 paramiko 的 `sftp.get(remote, local)`，流式传输。
- 传输前先 SFTP `stat()`，既能严格 cap 检查，也能给出干净的"远程文件不存在"错误而非传输途中的隐晦失败。
- **本地父目录必须存在**；Download **不**自动创建本地目录（与 Upload 不对称——Upload 会自动建远程父目录）。
- 本地文件按二进制方式写入。
- 传输期间阻塞；无进度上报。
- **传输中失败导致的残文件**：若网络中断或远程在 `get` 中途断开，paramiko 可能在 `local_path` 留下一个不完整的文件。Download **不**自动删除——无条件删除会破坏用户原本可能就存在的同名文件。中途失败返回 `Error:` 时，应把目标本地文件视为可能损坏。需要可恢复的传输请用 `Bash("rsync --partial --inplace ...", run_in_background=true)`。

## 带宽特征

- **传输大小**：等于远程文件字节数，受 SSH 压缩影响。
- **往返次数**：1 次 SFTP `stat`（cap 检查）+ 1 次 SFTP `get`。
- **阻塞对话**直到传输完成。大文件用 `Bash + scp` 后台模式。

## 相关

- [Upload](./upload.zh.md) —— 反向
- [Read](./read.zh.md) —— 服务器端按行切片；不写本地文件
- [Bash](./bash.zh.md) —— `scp` + `run_in_background=true` 模式
- [操作指南：运行长时后台任务](../../how-to/run-long-background-jobs.zh.md)
- Spec —— *不在 spec 中；v0.1.1 新增*
