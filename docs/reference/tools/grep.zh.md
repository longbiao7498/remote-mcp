# Grep

> English version: [grep.md](./grep.md)

使用服务端 `grep` 在远程主机上搜索文件内容中的扩展正则表达式。

## Schema

```json
{
  "type": "object",
  "properties": {
    "pattern":          {"type": "string"},
    "path":             {"type": "string"},
    "include":          {"type": "string", "default": ""},
    "case_insensitive": {"type": "boolean", "default": false},
    "before":           {"type": "integer", "default": 0},
    "after":            {"type": "integer", "default": 0},
    "context":          {"type": "integer", "default": 0},
    "head_limit":       {"type": "integer", "default": 200},
    "output_mode": {
      "type": "string",
      "enum": ["content", "files_with_matches", "count"],
      "default": "content"
    }
  },
  "required": ["pattern", "path"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `pattern` | string | 是 | — | 扩展正则表达式（`grep -E`）。 |
| `path` | string | 是 | — | 远程主机上的起始文件或目录。当为目录时递归搜索。 |
| `include` | string | 否 | `""` | 传递给 `--include` 的文件名 glob（如 `"*.py"`）。空字符串表示不过滤。 |
| `case_insensitive` | boolean | 否 | `false` | 为 `true` 时，向 `grep` 传递 `-i`。 |
| `before` | integer | 否 | `0` | 每个匹配前的上下文行数（`-B N`）。当 `context > 0` 或 `output_mode` 不是 `"content"` 时忽略。 |
| `after` | integer | 否 | `0` | 每个匹配后的上下文行数（`-A N`）。当 `context > 0` 或 `output_mode` 不是 `"content"` 时忽略。 |
| `context` | integer | 否 | `0` | 每个匹配前后的上下文行数（`-C N`）。大于 `0` 时覆盖 `before` 和 `after`。仅在 `output_mode="content"` 时适用。 |
| `head_limit` | integer | 否 | `200` | 返回的最大输出行数。通过服务端 `| head -<N>` 应用。 |
| `output_mode` | string | 否 | `"content"` | 控制 `grep` 的输出内容。详见下方输出模式表。 |

### 输出模式

| `output_mode` 值 | `grep` 标志 | 输出格式 |
|---|---|---|
| `"content"`（默认） | `-n` | `<path>:<lineno>:<matched line>`，每行一个匹配。设置 `before`/`after`/`context` 时，上下文行使用 `-` 作为分隔符。 |
| `"files_with_matches"` | `-l` | 每行一个文件路径。上下文参数被忽略。 |
| `"count"` | `-c` | 每个文件 `<path>:<count>`。上下文参数被忽略。 |

## 返回值

返回字符串。格式取决于执行结果：

**成功时：** 按 `output_mode` 描述的原始 `grep` 输出，截断至 `head_limit` 行。

**无匹配（退出码 1 或输出为空）：**

```
No matches found
```

**出错时：** 返回[错误措辞](#错误措辞)中列出的字符串之一。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `grep` 以退出码 `2` 退出（如无效正则、不可读路径） | `Error: <stderr text from grep>` |
| `output_mode` 不是三个有效值之一 | `Error: invalid output_mode: '<value>'. Must be one of ('content', 'files_with_matches', 'count').` |

## 行为说明

- 运行 `grep -r -E`（递归、扩展正则）。`-r` 标志始终存在。
- 上下文参数（`before`、`after`、`context`）仅在 `output_mode="content"` 时传递。在 `"files_with_matches"` 和 `"count"` 模式下这些参数被静默忽略——底层 `grep` 标志与 `-l` 和 `-c` 冲突。
- 当 `context > 0` 且 `before`/`after` 中一个或两个也被设置时，`context` 优先并覆盖两者。
- `include` 以 `--include=<value>` 传递。值在插入命令前经过 shell 引号处理。空字符串时完全省略该标志。
- `head_limit` 上限通过远程端的 `| head -<N>` 应用，在输出传输之前生效。它限制总输出行数，而非仅限匹配行——上下文行和 `grep` 分隔符行（`--`）计入上限。
- 不支持多行模式匹配。实现使用 POSIX `grep`，仅按行匹配。这是已记录的限制（spec §5.3.9）。
- 退出码 `1`（无匹配）和空 stdout 均映射为 `"No matches found"`。退出码 `0` 且有非空输出则原样透传。
- 通过 `conn.exec()` 运行——无状态的单次 SSH 通道，而非持久 bash 会话。

## 带宽特征

- 只有匹配行（加上所请求的上下文）通过网络传输。`head_limit` 对传输行数提供硬性上限。
- 每次调用使用一个无状态 `exec()` 通道。
- 当匹配文件数相对于匹配数较少时，使用 `output_mode="files_with_matches"` 或 `"count"` 可显著减少传输数据量。
- 上下文行（`-A/-B/-C`）可消除在需要周边行时对 [Read](./read.md) 的后续调用。

## 相关

- [Read](./read.md) — 在 grep 上下文不足时获取完整文件内容
- [Glob](./glob.md) — 按名称而非内容查找文件
- [Bash](./bash.md) — 运行该 Schema 无法表达的任意 `grep` 调用
- Spec §5.3.9
