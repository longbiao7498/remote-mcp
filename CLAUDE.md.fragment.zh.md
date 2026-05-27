> English version: [CLAUDE.md.fragment.md](./CLAUDE.md.fragment.md)

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
- 多步骤操作优先组合命令：`cmd1 && cmd2 && cmd3` 一次 Bash 调用。更复杂的逻辑写脚本（Write 上传 → Bash 执行）。
- 长耗时操作（build / 测试 / install / 大下载）**用 `Bash(command="...", run_in_background=true)`**，agent 不会被阻塞。
  - 工具返回会打印 PID、日志路径、4 条操作命令模板——**照抄即可**。
  - 用 `Read(log_path, offset=<last_line+1>)` 增量拉日志，不要 `Bash("cat log")`。
  - 任务做完或确定不要了，**务必用 `Bash("kill -TERM -- -<pid>")` 收尾**。
- 前台 Bash 长操作显式设大 timeout（如 600s）；可能拖到几分钟以上的直接用 `run_in_background`。
- 大输出命令要谨慎：`find /`、`ls -R /`、`grep -r 通用词 /` 会刷爆带宽，先想清楚再发。

### 多主机模式（2-3 台同时操作时）
- 工具调用结果会有 `[host=X cwd=Y]` 前缀，注意辨认当前操作的是哪台主机。
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
