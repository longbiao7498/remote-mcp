# Write

> English version: [write.md](./write.md)

通过 SFTP 将文本内容写入远程主机上的文件，按需创建父级目录。

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string"},
    "content": {"type": "string"}
  },
  "required": ["file_path", "content"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `file_path` | string | 是 | — | 远程主机上文件的绝对路径 |
| `content` | string | 是 | — | 要写入的文本内容（UTF-8 编码） |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** `Successfully wrote <N> characters to <file_path>`，其中 `<N>` 为 `len(content)`（Unicode 字符数，非字节数）。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 权限拒绝或其他 SFTP 写入失败 | `Error: <exception message from paramiko>` |

## 行为说明

- 文件通过 SFTP 二进制传输写入。整个 `content` 字符串以 UTF-8 编码，作为单次 SFTP 写入发送。传输层是二进制安全的，但 `content` 必须是有效的 UTF-8 文本；不支持二进制数据。
- 若文件已存在，则直接覆盖，不发出警告。没有追加模式。
- 父级目录通过纯 SFTP 操作（`sftp.stat` + `sftp.mkdir`）递归创建，不开启 shell 通道。每个目录层级在 mkdir 之前先进行 stat 检查；并发创建竞争被静默忽略。
- 成功字符串中的字符数 `<N>` 为 Python 中的 `len(content)`——Unicode 码点数量，对于非 ASCII 内容可能与字节长度不同。
- Write 不是原子操作：在 `sftp.file(file_path, "w")` 打开之后、写入完成之前发生失败，可能导致文件被截断。

## 带宽特征

- **传输大小：** 等于 `content` 的 UTF-8 字节长度，受 SSH 压缩影响。
- **往返次数：** 复用连接中已有的 SFTP 会话；无额外的 SSH exec 通道。
- **mkdir 开销：** 路径中每个尚不存在的目录层级需要一次 SFTP `stat` + 一次 `mkdir`。
- 请在调用 Write 之前组合好完整的文件内容，而非增量调用——每次调用都是独立的完整覆盖写入。

## 相关

- [Edit](./edit.md) — 替换现有文件中的子字符串，无需传输完整文件两次
- [MultiEdit](./multi-edit.md) — 在单次 SFTP 往返中对一个文件应用多处替换
- Spec §5.3.2
