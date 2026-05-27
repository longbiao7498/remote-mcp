# 错误措辞目录

> English version: [errors.md](./errors.md)

每个工具均返回字符串。失败情况下返回以 `"Error: "` 开头的字符串。以下是完整目录，包含精确措辞、发出该错误的工具，以及触发条件。

此措辞具有 API 稳定性——消费方（尤其是 Claude Code 的错误恢复逻辑）可能对这些字符串进行模式匹配。更改错误措辞属于破坏性变更。

## 按工具分类

### Read

| 触发条件 | 返回字符串 |
|---------|-----------|
| `offset` 参数小于 1 | `Error: offset must be >= 1, got <offset>` |
| `limit` 参数小于 1 | `Error: limit must be >= 1, got <limit>` |
| 文件不存在（`sed` 的 stderr 包含 "No such file" 或 "cannot open"） | `Error: File not found: <file_path>` |
| `sed` 以任何其他原因退出非零 | `Error: <stderr>` — 来自远程 `sed` 命令的 stderr，已去除首尾空白；当 stderr 为空时回退为 `Error: unknown error reading file` |

### Write

| 触发条件 | 返回字符串 |
|---------|-----------|
| 用户对 `<file_path>` 或其父目录无写权限（SFTP `PermissionError`，或 `errno=EACCES` 的 `IOError`） | `Error: Permission denied: <file_path>` |
| 其他 SFTP 写入失败（目标是目录、磁盘满、路径无效） | `Error: <message>` —— 底层异常的 `str()`；若 `str()` 为空则回退为异常类名 |

### Edit

| 触发条件 | 返回字符串 |
|---------|-----------|
| 文件不存在（SFTP 打开时 `IOError`） | `Error: File not found: <file_path>` |
| 文件中未找到 `old_string`（零次匹配，`replace_all=False`） | `Error: old_string not found in <file_path>` |
| 文件中未找到 `old_string`（零次匹配，`replace_all=True`） | `Error: old_string not found in <file_path>` |
| `old_string` 出现多次且 `replace_all=False` | `Error: old_string found <N> times in <file_path>. Provide more context to match uniquely, or set replace_all=true to replace all.` |

### MultiEdit

| 触发条件 | 返回字符串 |
|---------|-----------|
| `edits` 列表为空 | `Error: edits list is empty` |
| 文件不存在（SFTP 打开时 `IOError`） | `Error: File not found: <file_path>` |
| 第 N 条编辑的 `old_string` 未找到（零次匹配，`replace_all=False`） | `Error: edit #<N>: old_string not found` |
| 第 N 条编辑的 `old_string` 未找到（零次匹配，`replace_all=True`） | `Error: edit #<N>: old_string not found` |
| 第 N 条编辑的 `old_string` 出现多次且 `replace_all=False` | `Error: edit #<N>: old_string found <M> times. Provide more context or set replace_all=true.` |

### MultiRead

| 触发条件 | 返回字符串 |
|---------|-----------|
| `reads` 列表为空 | `Error: reads list is empty` |
| 远程命令退出非零且 stdout 为空 | `Error: <stderr>` — 来自远程 shell 的 stderr，已去除首尾空白；当 stderr 为空时回退为 `Error: multi_read failed` |

单个文件未找到不是 `"Error: ..."` 字符串——缺失文件会在合并输出中以 `===FILE: <path>===\nNOT_FOUND\n\n` 的形式内联报告。

### FileStat

| 触发条件 | 返回字符串 |
|---------|-----------|
| `file_paths` 为空列表 | `Error: file_paths is empty` |

单路径失败不是 `"Error: ..."` 字符串——它们以内联形式报告在结果中：
- 路径不存在：`<path>: exists=false`
- stat 时权限拒绝：`<path>: error=permission_denied`

### Bash

| 触发条件 | 返回字符串 |
|---------|-----------|
| 前台命令超时 | `Error: Command timed out after <timeout>s on <host>` |
| 后台启动超时（10 秒内部限制） | `Error: failed to launch background task on <host> (timeout)` |
| 后台启动成功但输出中未找到 `BG_PID=<n>` | `Error: failed to start background task on <host>. Output: <first 500 chars of output>` |

### Glob

| 触发条件 | 返回字符串 |
|---------|-----------|
| `find` 命令以 0 或 1 之外的退出码退出（如权限错误、无效路径） | `Error: <stderr>` — 来自远程 `find` 命令的 stderr，已去除首尾空白 |

无匹配不是错误：返回 `"No files found matching pattern"`（无 `"Error: "` 前缀）。

### Grep

| 触发条件 | 返回字符串 |
|---------|-----------|
| `output_mode` 不是 `"content"`、`"files_with_matches"`、`"count"` 之一 | `Error: invalid output_mode: <output_mode>. Must be one of ('content', 'files_with_matches', 'count').` |
| `grep` 以退出码 2 退出（grep 级别错误，如无效正则、不可读路径） | `Error: <stderr>` — 来自远程 `grep` 命令的 stderr，已去除首尾空白 |

无匹配（退出码 1 或 stdout 为空）不是错误：返回 `"No matches found"`（无 `"Error: "` 前缀）。

### Feedback

| 触发条件 | 返回字符串 |
|---------|-----------|
| `category` 不是 `"bug"` 或 `"enhancement"` | `Error: category must be 'bug' or 'enhancement', got <category>`（值经 `repr` 格式化，例如 `'other'`） |
| `summary` 为空或仅含空白字符 | `Error: summary cannot be empty` |

### 服务器 / 分发

| 触发条件 | 返回字符串 |
|---------|-----------|
| `_raw_dispatch` 无法识别工具名称 | `Error: unknown tool: <name>` |
| SSH 连接断开且重连失败 | `Error: SSH connection to <host> lost and reconnect failed: <reason>` |
| SSH 连接断开、重连成功，但重试的工具调用抛出异常 | `Error: <exception message>` |

## 横切说明

- **"文件未找到"的措辞因实现路径而异。** Read 通过 `exec` 使用 `sed`，通过检查 stderr 文本（`"No such file"`、`"cannot open"`）来检测文件缺失。Edit、MultiEdit 和 Write 使用 SFTP，通过 `IOError` 检测文件缺失。返回字符串相同（`Error: File not found: <path>`），但检测机制不同。
- **MultiEdit 的单条编辑错误内嵌编辑索引。** 格式 `Error: edit #<N>: ...` 使用 1-based 编号。在第一条失败的编辑处，操作中止，文件保持不变。其后的编辑（失败编辑之后）不再尝试。
- **MultiRead 的单文件未找到以内联形式呈现，而非错误前缀。** 单个 `NOT_FOUND` 条目嵌入在合并输出块中，不以 `"Error: ..."` 字符串返回。只有整个命令失败才会产生顶层 `"Error: ..."`。
- **FileStat 的单路径失败以内联形式呈现。** `exists=false` 和 `error=permission_denied` 作为普通结果中的行出现，不作为顶层 `"Error: ..."` 字符串。只有空 `file_paths` 列表才会产生顶层错误。
- **Bash 输出截断不是错误。** 当输出超过 `bash_output_cap` 时，输出会在原地截断，并追加 `\n... [truncated to <N> bytes]`。这是成功返回值的一部分。
- **Read 输出截断不是错误。** 当格式化后的输出超过 `read_size_cap` 时，追加 `\n... [truncated to <N> bytes]` 后缀。这是成功返回值的一部分。
- **重连 WARNING 不是错误前缀。** 当 SSH 连接断开且自动重连成功时，工具结果以 `[WARNING] SSH connection to <host> was lost and has been re-established. ...` 为前缀——该前缀追加到工具返回值（成功或错误）之前，而不是替换它。
- **Write 的 SFTP 异常不在工具层捕获。** `sftp.file()` 产生的权限拒绝等类似失败会传播到服务器重试路径，在那里以 `Error: <exception message>` 的形式呈现（包含原始 Python 异常文本）。
