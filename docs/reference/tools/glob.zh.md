# Glob

> English version: [glob.md](./glob.md)

使用服务端 `find` 在远程主机上查找匹配 glob 模式的文件。

## Schema

```json
{
  "type": "object",
  "properties": {
    "pattern": {"type": "string"},
    "path":    {"type": "string", "default": "."}
  },
  "required": ["pattern"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `pattern` | string | 是 | — | 用于匹配的 glob 模式（详见下方模式转换规则）。 |
| `path` | string | 否 | `"."` | 远程主机上搜索起始的根目录。远程绝对路径，或相对于已配置 cwd 的相对路径。不支持 ~（请使用绝对路径或相对路径）。 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** 以换行符分隔的匹配文件路径列表，按 `sort` 排序。每行一个路径。输出路径为绝对路径（如 `/opt/app/foo.py`）——已将解析后的搜索根目录纳入路径中。如需相对路径输出，请在 Bash 调用中使用 `cd <cwd> && find ...`。

MCP 服务器会在每次输出（成功和错误）后追加 `\n\n[host=X cwd=Y]`。工具本身的输出是该后缀之前的所有内容。

**无匹配：**

```
No files found matching pattern
```

**结果被截断：**

```
<path1>
<path2>
...
<pathN>
... [truncated to <N> entries]
```

上限为 `conn.config.glob_output_limit`（默认 `1000`）。当匹配数超过上限时，仅返回前 `N` 个有序路径，并附加截断说明。

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `find` 以 `0` 或 `1` 之外的退出码退出（如无效路径、权限错误） | `Error: <stderr text from find>` |

## 行为说明

### 模式到 `find` 的转换

glob 模式按以下规则转换为 `find` 表达式：

| 模式形式 | 转换后的 `find` 表达式 | 说明 |
|---|---|---|
| `*.ext` | `-name '*.ext'` | 无路径分隔符：在任意深度匹配文件名 |
| `**/*.ext` | `-name '*.ext'` | 前缀 `**/` 且尾部无 `/`：视为仅文件名匹配 |
| `dir/*.ext` | `-wholename '*/dir/*.ext'` | 保留路径段；添加前缀 `*/` 使匹配与深度无关 |
| `dir/**/*.ext` | `-wholename '*/dir/*/*.ext'` | `**` 折叠为 `*`；保留路径段 |

`find` 命令始终包含 `-type f`——目录和符号链接不在结果中。

### `**` 语义

`**`（globstar）是近似实现：在 `find -wholename` 中折叠为 `*`。这意味着 `**` 可以在任意深度匹配，但不像 shell globstar 那样能跨越多个路径段。例如，`src/**/*.py` 会匹配 `src/a/b.py`，但根据路径深度不同，可能无法匹配 `src/a/b/c.py`。这是已记录的限制（spec §9）。

### 截断行为

`find` 通过 `head -<limit+1>` 管道传输。若返回超过 `limit` 行，输出截断为 `limit` 条并追加截断说明。截断在返回调用方前执行。

### stderr 抑制

`find` 的错误（如对某个子目录 `Permission denied`）通过 `2>/dev/null` 重定向到 `/dev/null`。只有结构性 `find` 失败（非 0、非 1 的退出码）才以错误形式呈现。来自可访问目录的部分结果仍会返回。

## 带宽特征

- `find` 命令完全在远程主机上运行。只有匹配路径列表通过网络传输。
- 每次调用使用一个无状态 `exec()` 通道（而非持久 bash 会话）。
- 在搜索大型目录树时，将 `path` 参数缩小到特定子目录，可减少远程 CPU 消耗和结果大小。

## 相关

- [Grep](./grep.md) — 搜索文件内容而非文件名
- [Bash](./bash.md) — 运行模式语法无法表达的任意 `find` 表达式
- [FileStat](./file-stat.md) — 检查已知路径的存在性和元数据
- Spec §5.3.8
