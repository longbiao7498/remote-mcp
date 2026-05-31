# JobScript

> English version: [job-script.md](./job-script.md)

为面板跟踪的任务挂载（或清除）自定义 bash 状态脚本。每次以单任务模式调用 `Jobs(name=X)` 或 `Jobs(id=N)` 时，该脚本自动在远端执行。

## Schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "任务名称。与 id 互斥。"
    },
    "id": {
      "type": "integer",
      "description": "任务 id。与 name 互斥。"
    },
    "script": {
      "type": "string",
      "description": "Bash 脚本正文。本地存储于 ~/.local/share/remote-mcp/jobpane/<sid>/<host>/<id>-status.sh（真相来源），并上传至远端 ~/.cache/remote-mcp-<sid>-<id>-status.sh（缓存；Jobs 若发现缺失会自动重新上传）。每次 Jobs(name=X) 单任务查询时在远端执行。传入空字符串 '' 表示清除（仅删除本地源文件；远端缓存保留但不再引用）。脚本通过 'bash --noprofile --norc' 运行，并 source 快照；可通过 'cat ~/.cache/remote-mcp-<sid>-<id>-pid' 或 pgrep 模式获取 $PID。"
    },
    "timeout": {
      "type": "integer",
      "description": "必填。超时秒数。根据脚本功能选择：简单 pgrep+tail+ls=5；读取共享 FS 上的大日志=30；调用 squeue/kubectl/网络服务=60。超时立即关闭通道。以 script_timeout 存入 meta.json，每次 Jobs(name=X) 调用时复用。"
    }
  },
  "required": ["script", "timeout"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `name` | string | 否 | — | 任务别名。与 `id` 互斥。`name` 与 `id` 二者必须提供其一。 |
| `id` | integer | 否 | — | 任务 id。与 `name` 互斥。 |
| `script` | string | 是 | — | 脚本正文。传入 `""` 表示清除脚本。 |
| `timeout` | integer | 是 | — | 执行超时秒数。无默认值——强制 agent 思考脚本的执行时间。以 `script_timeout` 存入 meta，并被后续每次 `Jobs(name=X)` 调用复用。 |

`script` 与 `timeout` 始终必填——`script=""` 加任意 `timeout` 即可清除脚本（清除时 timeout 被忽略）。

## 返回值

### 脚本挂载成功（exit_code 为 0）

```
Status script attached to 'x86_python_build' (id=17).
First-run validation:
  exit_code: 0
  elapsed_sec: 1
  stdout: |
    pid=1259443 alive
    progress=26/42
  stderr: (empty)

[host=tjcs_ex_ln3 cwd=/home/user]
```

### 脚本挂载成功但首次运行退出码非零

```
Status script attached to 'x86_python_build' (id=17). NOTE: first-run
exited with non-zero code. The script is still attached (non-zero exit
may be intentional, e.g. 'task not yet in expected phase'). Verify the
output below matches your intent; call JobScript again with the same
name to replace.

First-run validation:
  exit_code: 2
  elapsed_sec: 1
  stdout: ...
  stderr: ...

[host=tjcs_ex_ln3 cwd=/home/user]
```

### 首次运行超时——脚本被拒绝

```
Error: status script first-run timed out after 30s on tjcs_ex_ln3.
Script has been removed (both local source and remote cache); status
script for 'x86_python_build' is now empty. Likely causes: script
logic too slow, or timeout too tight. Adjust and call JobScript again.

[host=tjcs_ex_ln3 cwd=/home/user]
```

### 脚本已清除（`script=""`）

```
Status script cleared for 'x86_python_build' (id=17).
(Remote cache file at ~/.cache/remote-mcp-<sid>-17-status.sh is left
in place but no longer referenced; it will be overwritten if you
attach a new script.)

[host=tjcs_ex_ln3 cwd=/home/user]
```

## 行为说明

- **本地真相来源**：脚本正文写入 MCP host 本地的 `~/.local/share/remote-mcp/jobpane/<sid>/<host>/<id>-status.sh`。远端文件（`~/.cache/remote-mcp-<sid>-<id>-status.sh`）为缓存。
- **自动重新上传**：`Jobs(name=X)` 运行脚本时若远端缓存缺失，自动从本地源重新上传。外部清理 `~/.cache/` 不会永久破坏脚本功能。
- **首次运行验证**：`script != ""` 时，JobScript 上传脚本并执行一次。首次运行超时 = 脚本被拒绝并清理（本地与远端均清理）。首次运行非零退出码 = 脚本被接受并附带提示（agent 验证输出是否符合预期）。
- **清除语义**：`script=""` 删除本地源文件，并将 `meta.script_timeout` 设为 null。远端缓存保留（下次 `JobScript` 设置时覆盖）。已清除的脚本不会被后续 `Jobs` 调用执行。
- **脚本执行环境**：脚本通过 `exec_with_snapshot` 运行，快照（PATH、别名、配置的 cwd）在脚本中生效。在脚本中引用任务 PID：`cat ~/.cache/remote-mcp-<sid>-<id>-pid` 或 `pgrep -f <模式>`。
- **超时复用**：`timeout` 值以 `script_timeout` 存入 meta，后续每次 `Jobs(name=X)` 单任务调用均复用此值。如需修改超时，以相同脚本内容和新超时值再次调用 `JobScript`。
- **已归档任务**：对已归档任务调用 JobScript 返回 Error。

## 设计意图

状态脚本让 agent 通过单次 `Jobs(name=X)` 调用获得丰富的结构化状态信息，而无需执行多步的 `pgrep + tail + ls + squeue` 组合。一个良好编写的状态脚本仅输出 agent 判断"仍在运行 / 已完成 / 需要关注"所需的字段——无需通过网络传输大量日志文件。

Python build 场景的示例脚本：

```bash
#!/bin/bash
PID=$(cat ~/.cache/remote-mcp-XXXX-17-pid 2>/dev/null)
if kill -0 "$PID" 2>/dev/null; then
    echo "pid=$PID alive"
fi
PROG=$(grep -c 'Compiling' ~/build.log 2>/dev/null || echo 0)
echo "progress=$PROG objects compiled"
ls ~/install/Python-3.13.4/bin/python3 2>/dev/null && echo "artifact=ready" || echo "artifact=not_yet"
```

## 路由

JobScript 在 `NO_RETRY_TOOLS` 中——它上传文件并执行，两者均为非幂等副作用，不应自动重试。

## 相关

- [Jobs](./jobs.md) — 单任务模式下运行挂载的状态脚本
- [Bash](./bash.md) — 启动后台任务
- 规范 §9
