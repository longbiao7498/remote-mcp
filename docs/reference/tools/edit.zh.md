# Edit

> English version: [edit.md](./edit.md)

通过 SFTP 读-改-写方式替换远程文件中的精确子字符串，默认执行唯一性检查。

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string"},
    "old_string": {"type": "string"},
    "new_string": {"type": "string"},
    "replace_all": {"type": "boolean", "default": false}
  },
  "required": ["file_path", "old_string", "new_string"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `file_path` | string | 是 | — | 远程主机上文件的绝对路径 |
| `old_string` | string | 是 | — | 要替换的精确子字符串 |
| `new_string` | string | 是 | — | 替换后的子字符串 |
| `replace_all` | boolean | 否 | `false` | 若为 `true`，替换所有出现的位置；跳过唯一性检查 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** `Successfully edited <file_path>`

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 文件不存在 | `Error: File not found: <file_path>` |
| 文件中未找到 `old_string` | `Error: old_string not found in <file_path>` |
| `old_string` 出现多次且 `replace_all` 为 `false` | `Error: old_string found <N> times in <file_path> (lines <L1, L2, ...>). Provide more context to match uniquely, or set replace_all=true to replace all.` |

## 行为说明

- 文件通过 SFTP 完整读取，在内存中修改，然后通过 SFTP 完整写回。读写操作均传输完整的文件内容。
- **唯一性检查（默认行为，`replace_all=false`）：** `old_string` 必须在文件中恰好出现一次。零次匹配和多次匹配均会产生错误，文件保持不变。
- **`replace_all=true`：** 通过单次 `str.replace()` 调用替换所有出现位置。零次匹配仍会返回错误。
- 出现任何错误（文件未找到、零次匹配、匹配不唯一）时，**文件不会被写入**。错误路径不会产生任何中间状态。
- Edit 不防范并发写入。同一时间只有一个 agent 操作某个文件才是安全的。
- 对同一文件进行多处替换时，[MultiEdit](./multi-edit.md) 只需读写文件一次，而非每次替换各读写一次。
- 文件必须是有效的 UTF-8 编码。不支持二进制文件。

## 带宽特征

- **传输大小：** 每次 Edit 调用完整读取一次、完整写入一次。对于 50 KB 的源文件，每次 Edit 共传输约 100 KB（读 + 写），受 SSH 压缩影响。
- **往返次数：** 在共享 SFTP 会话上进行两次 SFTP 操作（读 + 写）；无额外的 exec 通道。
- **替代方案：** [MultiEdit](./multi-edit.md) 将同一文件的 N 次编辑压缩为一次读 + 一次写。

## 相关

- [MultiEdit](./multi-edit.md) — 原子性地对单个文件应用多处编辑
- [Write](./write.md) — 覆盖整个文件
- [Read](./read.md) — 读取文件中的行
- Spec §5.3.3
