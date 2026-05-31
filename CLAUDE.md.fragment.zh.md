> English version: [CLAUDE.md.fragment.md](./CLAUDE.md.fragment.md)

## remote-mcp v0.2.0 行为说明（shell + 路径）

- **Bash 非持久**：`cd dir`、`export FOO=bar`、`source venv/bin/activate` 跨调用**不**保留。链式操作请内联完成：`cd dir && cmd`、`FOO=bar cmd`、`venv/bin/python script.py`。
- **路径可以是相对的**：所有文件/搜索工具接受相对于配置 `cwd`（`--cwd /opt/app`）的路径。`Read("config.yaml")` 读取 `/opt/app/config.yaml`。工具参数中**不允许** `~` ——使用绝对路径或相对 cwd 的路径。当前 cwd 会出现在每个工具的输出末尾：`[host=X cwd=Y]`。
- **Glob/Grep 输出**：绝对路径（如 `/opt/app/foo.py`）——可直接喂给 Read/Edit，无需拼接。

## 在远程主机上工作（remote-mcp 工具使用指南）

本项目通过 `mcp__remote-<host>__` 系列工具操控远程服务器。SSH 链路带宽有限、延迟较高。
请遵循以下工作流：

### 单主机模式

**查代码 / 探索仓库**
- 查代码先用 Grep 定位关键字。如果需要看上下文，**直接用 Grep 的 `context=5`（或 before/after）一次拿到匹配 + 周围代码**，不要 Grep 后再 Read 跟进。
- 只想知道某个文件存在吗、多大、什么时候改的？**用 FileStat**，不要 Read 试探（可能传输 50MB 只为知道文件不该读）。
- 探索多个相关文件（如 config / models / utils 一组）**一次 MultiRead 调用**，不要连续 Read。

**编辑文件**
- 同一文件多处修改，**一律用 MultiEdit**，禁止连续 Edit。

**Shell 操作**
- **shell 状态跨调用不持久。** 每次 Bash 调用都是一个全新的 shell，从配置的 cwd 开始。`cd`、`export`、`source venv/bin/activate` 只在当次调用内生效。
- 需要共享状态的多步操作，请在一次调用内链式完成：`cd dir && cmd1 && cmd2`。激活 venv 并运行命令：`venv/bin/python script.py` 或 `. venv/bin/activate && python script.py`——全部在一次 Bash 调用内。
- 更复杂的逻辑写脚本（Write 上传 → Bash 执行）。
- 长耗时操作（build / 测试 / install / 大下载）**用 `Bash(command="...", run_in_background=true, name="my-build", log_path="/home/user/my-build.log")`**，agent 不会被阻塞。
  - v0.3.0 面板工作流：
    1. **启动**：`Bash(run_in_background=True, name="X", log_path="/home/user/X.log", command="bash ~/X.sh")` — 返回 `id`、`pid`、`log_path`。
    2. **查询状态**：`Jobs(name="X")` — 观察远端存活状态，更新状态缓存。或 `Jobs()` 列出所有任务。
    3. **读取日志**：`Read("/home/user/X.log", offset=<last_line+1>)` — 增量轮询，不要 `Bash("cat log")`。
    4. **Kill**：`JobKill(name="X")` — 默认 `kill -TERM -- -<pgid>`；Slurm 场景用 `JobKill(name="X", kill_cmd="scancel 12345")`。
    5. **完成后归档**：`Jobs(name="X")` 显示 `stopped` 或 `killed` 且已查看日志后，调用 `JobArchive(name="X")` 释放名称。
    6. **kill 失败时**：经过 ≥ 3 次失败的 `JobKill` 后，可放弃管理并调用 `JobArchive(name="X", as_zombie=True)`。
    7. **CC 重启后面板消失**：用 `Bash("ls ~/.cache/remote-mcp-*-pid")` 查找旧 session 遗留的远端 pid 文件。
  - 可选：挂载状态脚本以实现单次调用的丰富状态查询：`JobScript(name="X", script="...", timeout=10)` — 每次 `Jobs(name="X")` 调用时自动运行。
- 前台 Bash 长操作显式设大 timeout（如 600s）；可能拖到几分钟以上的直接用 `run_in_background`。
- 大输出命令要谨慎：`find /`、`ls -R /`、`grep -r 通用词 /` 会刷爆带宽，先想清楚再发。
- 文件传输（二进制或大文件）：**优先 `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** 而不是 `Upload` / `Download` 工具。scp/rsync 在后台模式下非阻塞、不限大小。`Upload`/`Download` 是给 PATH 中无 scp 的 Windows 用户的兜底，且受 `transfer_size_cap` 限制（默认 100 MB）。Linux/macOS 上 scp 在每个维度都更好。

### 多主机模式（2-3 台同时操作时）
- 工具调用结果末尾会有 `[host=X cwd=Y]` 后缀，注意辨认当前操作的是哪台主机。
- 尽量把工作集中在单台主机上完成；跨主机协调需求增加错误率。
- 跨主机文件传输：用 Bash 调 `scp <local>:<path> <remote>:<path>`（需用户预先在主机间配好 SSH 互信）。**禁止** Read-本地中转-Write 的"双跳"模式。
- 看到 `[WARNING] SSH connection to <host> was lost` 时，状态丢失仅限那台主机。

### 持续反馈（Continuous improvement feedback）

remote-mcp 提供 `Feedback` 工具，让你（agent）把使用过程中遇到的问题或灵感沉淀下来。

✅ **DO**：
- 某个 remote-mcp 工具的行为不符合 Claude Code 原生工具的预期
- 某个工具有 bug：超时反常、输出损坏、结果与文档不符
- 你想到："如果有 X 工具或 Y 参数会让这件事简单很多"——具体到能描述 API
- 工作流摩擦：某场景需要 3+ 次工具调用才能完成

❌ **DON'T**：
- 用户代码里的 bug（应该改用户代码）
- 远程系统问题（应该写到运维记录里）
- 不基于实际遇到情况的猜测

**调用规范**：
- `category="bug"` 配实际复现描述
- `category="enhancement"` 配具体到能 mock API
- **不打断当前任务**：file 完一条 feedback 就继续手头的事
- summary 一行；details 写背景

**隐私**：写入本地 `~/.local/share/remote-mcp/feedback.jsonl`，不上传任何地方。

## remote-mcp v0.2.2 行为说明（网络异常）

- **`Error: SSH channel ... closed unexpectedly`**：远端命令的执行状态不可确定。幂等读类（`cat`、`ls`、`pwd`、`grep`）可直接重发；副作用类（`rm`、`mv`、`git push`、迁移脚本等）应先通过其他工具查证状态（`Read` / `Bash("ls ...")`）再决定是否重发；长任务（`sleep`、训练脚本等）可能仍在远端运行——用 `Bash("pgrep -af <命令片段>")` 查证。

- **`Error: SSH connection ... reconnect failed`**：网络真的不通。等待几秒后再发任何调用；或先调一次 `RemoteInfo`（不走网络）作为最低成本的"是否恢复"探测。

- **`Error: Edit ... old_string not found`** 紧接在最近一次 `[WARNING] SSH connection was lost` 之后：之前的 Edit 可能实际已成功——Edit / MultiEdit 明确**不**自动重试（v0.2.2 spec bug #1）。重新 Edit 前先 Read 文件确认状态。如果文件已是期望状态，不要重发 Edit。

- **`[WARNING] ... snapshot ... missing AND re-upload failed`**：后续 Bash 调用不加载用户 PATH/aliases、工作目录回退至 `$HOME`。对依赖用户环境的命令使用绝对路径（如 `/home/user/miniconda3/bin/conda` 代替 `conda`），直到下次 MCP 服务重启为止。

- **后台任务启动失败响应丢失时**：工具自动回退到 SFTP 读取远端 pid 文件。两者均失败时，任务**不**进入面板，返回 Error 并附回收指引。如需查找孤儿远端进程，使用：
  ```bash
  Bash("ls ~/.cache/remote-mcp-*-pid 2>/dev/null")
  Bash("for f in ~/.cache/remote-mcp-*-pid; do pid=$(cat $f); kill -0 $pid 2>/dev/null && echo \"$f: pid=$pid ALIVE\"; done")
  ```
