# FileStat

> English version: [file-stat.md](./file-stat.md)

获取一个或多个远程路径的元数据（存在性、大小、mtime、mode），无需传输文件内容。

## Schema

```json
{
  "type": "object",
  "properties": {
    "file_paths": {
      "oneOf": [
        {"type": "string"},
        {"type": "array", "items": {"type": "string"}}
      ]
    }
  },
  "required": ["file_paths"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `file_paths` | string or array of strings | 是 | — | 要 stat 的远程主机上的单个路径或路径列表 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** 每个路径对应一行，顺序与输入一致：

```
<path>: exists=true type=<kind> size=<bytes> mode=<octal4> mtime=<iso8601>
```

- `kind` 为 `file`、`dir` 或 `symlink` 之一。
- `mode` 为原始 mode 位的最后四位八进制数字（如 `0644`）。
- `mtime` 为 UTC ISO 8601，秒精度（如 `2026-05-26T10:00:00+00:00`）。

**路径不存在：**

```
<path>: exists=false
```

**权限错误：**

```
<path>: error=permission_denied
```

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `file_paths` 为空列表 | `Error: file_paths is empty` |

单个路径的错误（不存在、权限拒绝）以内联形式出现在输出中，而非作为顶层错误返回——详见上方"返回值"。

## 行为说明

- 接受裸字符串或 JSON 数组。单个字符串内部归一化为单元素列表。
- 使用已打开的 SFTP 客户端上的 `stat()`——每次调用不开启新的 SSH 通道。
- 结果按输入 `file_paths` 的顺序返回。
- `symlink` 通过对原始 mode 位调用 `S_ISLNK()` 来检测。SFTP `stat()` 默认跟随符号链接；报告的类型反映链接目标，而非链接本身——除非 stat 调用的是悬空符号链接（此时报告为 `exists=false`）。
- `mode` 字段仅包含最后四位八进制数字（如 `0755`，而非 `0o100755`）。
- `mtime` 为时区感知的 UTC；始终带有 `+00:00` 后缀。
- 该工具不抛出异常。所有单路径失败均折叠进返回字符串中。

## 带宽特征

- 每个路径 stat 操作是复用 SFTP 通道上的一条 SFTP 消息——每个路径通常交换不到 100 字节。
- 在单次调用中批量处理多个路径，相比用 [Bash](./bash.md) `stat` 逐个查询可避免多次往返。
- 无论文件大小如何均不传输文件内容。在决定是否调用 [Read](./read.md) 之前，可先用 FileStat 探测大文件。

## 相关

- [Read](./read.md) — 用 FileStat 确认大小后读取文件内容
- [Bash](./bash.md) — 获取 FileStat 未暴露的元数据（如符号链接目标、扩展属性）
- Spec §5.3.6
