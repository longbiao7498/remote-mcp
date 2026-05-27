# Read

> English version: [read.md](./read.md)

使用服务端 `sed` 切片读取远程主机上文件中的行。

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string",
      "description": "Absolute path to the file on the remote server"
    },
    "offset": {
      "type": "integer",
      "description": "Start line number (1-based). Default: 1",
      "default": 1
    },
    "limit": {
      "type": "integer",
      "description": "Max lines to read. Default: 2000",
      "default": 2000
    }
  },
  "required": ["file_path"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `file_path` | string | 是 | — | 远程主机上文件的绝对路径 |
| `offset` | integer | 否 | `1` | 返回的起始行（1-based）。必须 >= 1。 |
| `limit` | integer | 否 | `2000` | 返回的最大行数。必须 >= 1。 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** 每行以格式 `     <lineno>\t<content>` 加 1-based 行号为前缀（五个空格、行号、制表符，然后是包含换行符的原始行内容）。行号从 `offset` 开始计数。若格式化后的输出超过 `read_size_cap`（默认 256 KB），则在字节边界处截断并追加说明：`\n... [truncated to <N> bytes]`。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `offset` 参数小于 1 | `Error: offset must be >= 1, got <offset>` |
| `limit` 参数小于 1 | `Error: limit must be >= 1, got <limit>` |
| 远程主机上文件不存在 | `Error: File not found: <file_path>` |
| 任何其他 `sed` / SSH 执行错误 | `Error: <stderr text>` 或 `Error: unknown error reading file` |

## 行为说明

- 在服务端使用 `sed -n '<offset>,<end>p; <end+1>q'`。只有所请求的行通过网络传输。从 100 MB 文件中读取 20 行，只传输那 20 行。
- 远程命令通过 `conn.exec()` 运行——无状态的单次 SSH 通道，而非持久 bash 会话。
- 来自远程 `sed` 调用的 `stderr` 合并到错误字符串中。该工具不抛出异常。
- 若文件的行数少于请求的行数，只返回可用的行；不产生错误。
- 大小上限在行号格式化之后应用。格式化输出超过 256 KB 的文件在输出中途被截断；最后一个不完整行可能被截断。
- 如需在不传输内容的情况下检查文件是否存在或获取其大小，请使用 [FileStat](./file-stat.md)。

## 带宽特征

- **传输大小：** 与所请求的行数成正比，而非文件大小。读取典型源文件的 2000 行传输 50–150 KB。
- **往返次数：** 每次调用使用一个 SSH exec 通道。
- **压缩：** SSH 级别压缩默认启用；文本内容通常压缩 3–10 倍。
- **替代方案：** [MultiRead](./multi-read.md) 将多个文件读取批量合并为单次往返。

## 相关

- [MultiRead](./multi-read.md) — 在单次往返中批量读取多个文件
- [FileStat](./file-stat.md) — 无需传输内容即可检查存在性和大小
- [Grep](./grep.md) — 搜索特定文本，只返回匹配行
- Spec §5.3.1
