# MultiEdit

> English version: [multi-edit.md](./multi-edit.md)

在单次 SFTP 读写周期内，原子性地对单个远程文件应用一系列字符串替换。

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string"},
    "edits": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "old_string": {"type": "string"},
          "new_string": {"type": "string"},
          "replace_all": {"type": "boolean", "default": false}
        },
        "required": ["old_string", "new_string"]
      }
    }
  },
  "required": ["file_path", "edits"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `file_path` | string | 是 | — | 远程绝对路径，或相对于已配置 cwd 的相对路径。不支持 ~（请使用绝对路径或相对路径）。 |
| `edits` | array | 是 | — | 要依次应用的编辑对象列表 |
| `edits[].old_string` | string | 是 | — | 要替换的精确子字符串 |
| `edits[].new_string` | string | 是 | — | 替换后的子字符串 |
| `edits[].replace_all` | boolean | 否 | `false` | 若为 `true`，替换该条编辑的 `old_string` 的所有出现位置 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** `Successfully applied <N> edits to <file_path>`，其中 `<N>` 为列表中的编辑数量。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

MCP 服务器会在每次输出（成功和错误）后追加 `\n\n[host=X cwd=Y]`。工具本身的输出是该后缀之前的所有内容。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `edits` 列表为空 | `Error: edits list is empty` |
| 文件不存在 | `Error: File not found: <file_path>` |
| 第 #N 条编辑的 `old_string` 未找到（包括在前序编辑应用后的情况） | `Error: edit #N: old_string not found` |
| 第 #N 条编辑的 `old_string` 出现多次且 `replace_all` 为 `false` | `Error: edit #<N>: old_string found <M> times (lines <L1, L2, ...>). Provide more context or set replace_all=true.` |

## 行为说明

- **单次 SFTP 周期：** 文件读取一次，所有编辑在内存中按顺序应用，然后文件写入一次。编辑之间不重新读取文件。
- **原子性：** 若序列中任意一条编辑失败（未找到、匹配不唯一），整个操作中止。文件保持不变。不会写入任何部分编辑结果。
- **编辑顺序至关重要：** 编辑按序应用于运行中的内容。第 #2 条编辑在第 #1 条编辑产生的内容上操作。第 #2 条编辑的 `old_string` 匹配是针对已修改内容进行的，而非原始内容。
- 每条编辑的 `replace_all` 标志独立生效。`replace_all=true` 的编辑会替换该时间点内容中其 `old_string` 的每一处出现。
- 错误消息中的编辑索引从 1 开始（`edit #1`、`edit #2`……）。
- 文件必须是有效的 UTF-8 编码。不支持二进制文件。
- MultiEdit 不防范并发写入。
- **网络故障不会自动重试。** v0.2.2：若 SSH 在 MultiEdit 执行过程中断开，agent 将收到 `Error: <ExceptionType>: <message>`，下一次工具调用会触发重连。MultiEdit **不会**自动重试，因为读-改-写的语义使其不安全——重新执行会看到已被修改的文件，并错误地报告 `old_string not found`。Agent 应先通过 `Read` 读取文件，确认首次操作是否已成功。

## 带宽特征

- **传输大小：** 无论列表中有多少条编辑，文件仅读取一次、写入一次。对同一文件进行 N 条编辑，MultiEdit 的网络传输成本与单次 [Edit](./edit.md) 调用相同。
- **往返次数：** 在共享 SFTP 会话上进行两次 SFTP 操作；无 exec 通道。
- **对比：** 对同一文件进行 N 次独立 [Edit](./edit.md) 调用需要 2N 次 SFTP 传输。N 条编辑的 MultiEdit 仅需 2 次。

## 相关

- [Edit](./edit.md) — 单处替换；一条编辑的唯一性语义与此相同
- [Write](./write.md) — 覆盖整个文件
- [Read](./read.md) — 读取文件中的行
- Spec §5.3.4
