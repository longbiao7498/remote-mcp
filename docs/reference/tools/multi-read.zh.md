# MultiRead

> English version: [multi-read.md](./multi-read.md)

通过一次组合的服务端 shell 脚本，在单次 SSH 往返中读取多个远程文件。

## Schema

```json
{
  "type": "object",
  "properties": {
    "reads": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "file_path": {"type": "string"},
          "offset": {"type": "integer", "default": 1},
          "limit": {"type": "integer", "default": 2000}
        },
        "required": ["file_path"]
      }
    }
  },
  "required": ["reads"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `reads` | array | 是 | — | 有序的文件读取描述符列表 |
| `reads[].file_path` | string | 是 | — | 远程主机上文件的绝对路径 |
| `reads[].offset` | integer | 否 | `1` | 返回的起始行（1-based） |
| `reads[].limit` | integer | 否 | `2000` | 该文件返回的最大行数 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** 由标题行分隔的各文件内容片段拼接而成的字符串。每个文件片段格式如下：

```
===FILE: <file_path>===
     <lineno>\t<line>
     <lineno>\t<line>
     ...

```

不存在的文件表示为：

```
===FILE: <file_path>===
NOT_FOUND

```

每个片段内的行号从 1-based 开始，从该读取条目的 `offset` 值起计。整体输出上限为 `read_size_cap` 字节（默认 256 KB）；达到上限时在字节边界处截断，并追加 `\n... [truncated to <N> bytes]`。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `reads` 列表为空 | `Error: reads list is empty` |
| 远程 exec 命令失败且不产生 stdout | `Error: <stderr text>` 或 `Error: multi_read failed` |

## 行为说明

- 在客户端构造单个 shell 脚本，通过一次 `conn.exec()` 调用发送到远程主机。脚本发出内部标记 `===RMCP_FILE_BEGIN:...===` 和 `===RMCP_FILE_END:...:(OK|NOT_FOUND)===`，由客户端解析；这些标记不会出现在返回的输出中。
- 服务端切片：每个文件使用 `sed -n '<offset>,<end>p; <end+1>q'`。只有所请求的行通过网络传输，而非完整文件。
- 文件存在性通过 shell 脚本中的 `[ -f <file_path> ]` 测试。存在但为目录的路径将报告为 `NOT_FOUND`。
- 大小上限应用于所有文件的最终格式化输出，而非每个文件单独计算。列表中靠前的文件在达到上限时更可能被完整包含。
- `conn.exec()` 调用对组合脚本使用 60 秒超时。涉及非常大的文件或大量文件的请求可能较慢。
- 行号格式与 [Read](./read.md) 一致：五个空格、行号（从 `offset` 开始）、制表符、然后是原始行内容。
- 内部标记（`===RMCP_FILE_BEGIN:...===`、`===RMCP_FILE_END:...===`）不保证在文件内容中缺席；恰好在行首包含字面字符串 `===RMCP_FILE_BEGIN:` 的文件可能导致解析异常。这是一个边界情况。

## 带宽特征

- **往返次数：** 无论文件数量多少，使用一个 SSH exec 通道。
- **传输大小：** 与所有文件请求行范围之和成正比，受 SSH 压缩影响。
- **对比：** N 次独立 [Read](./read.md) 调用各消耗一次往返；N 个条目的 MultiRead 仅消耗一次。在 500 ms RTT 的链路上，分别读取五个文件至少需要 2.5 秒的纯延迟；MultiRead 最多约 0.5 秒。

## 相关

- [Read](./read.md) — 读取单个文件的行
- [FileStat](./file-stat.md) — 无需传输内容即可检查多个文件的存在性和大小
- [Grep](./grep.md) — 在多个文件中进行服务端搜索
- Spec §5.3.5
