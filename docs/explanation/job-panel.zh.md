# 任务面板：设计理念

> English version: [job-panel.md](./job-panel.md)

本文阐述 v0.3.0 后台任务面板的设计决策——架构为何如此组织、哪些备选方案被否决，以及每项选择带来的后果。修改面板子系统之前请先阅读本文。

规范性规格见 [`docs/superpowers/specs/2026-05-31-v0.3.0-job-panel.md`](../superpowers/specs/2026-05-31-v0.3.0-job-panel.md)（§4、§7、§10、§11）。

## 为何采用本地优先的元数据存储

面板元数据（`<id>-meta.json`）与状态脚本源文件（`<id>-status.sh`）存储在 MCP 宿主机上——即运行 Claude Code 的本地机器——而非远端主机。远端文件仅限三类：pid 文件、status.sh 缓存，以及日志文件。

**原因是延迟。** MCP 服务器是长生命周期进程；每次"查询面板"的工具调用在整个 session 期间可能反复触发。若面板查询需要通过 SSH 往返读取远端状态，每次 `Jobs()`、`JobKill`、`JobArchive` 都要承担这个开销（学术集群上通常 20–200 ms）。若同时有 10 个面板任务，列表模式将需要 10 次并行 stat 调用或一条复合 bash 管道——全部可以避免。

本地文件 IO 几乎没有成本。代价是元数据不能在 MCP 宿主机重启或进程迁移后存活；这是可接受的，因为面板的生命周期明确绑定于 Claude Code 会话。

另一个好处：**JobArchive 完全是本地操作**。由于权威状态存储在本地，归档一个任务就是将 JSON 文件 `mv` 到目标目录，并可选地 `mv` 一个 shell 脚本。无需 SSH 连接，也不存在"归档时远端恰好不可达"的边界情况。

## 为何采用基于 id 的目录命名（而非基于 name）

每个任务获得一个单调递增的整数 `id`，而非以其别名（`name`）命名的目录。别名作为 `<id>-meta.json` 内的一个字段存储。

**这允许归档后安全地复用同一名称。** 典型的长时任务工作流会反复启动同名任务（"python-build"、"train-run-1" 等）。若目录以别名命名，归档时就需要重命名目录并使所有现有引用失效。采用基于 id 的命名后，归档仅是 `mv 17-meta.json archive/17-meta.json`——名称立即从活跃命名空间释放，旧任务仍可通过 `Jobs(id=17)` 在新位置（`archive/`）查询。

`archive/` 与 `zombie/` 子目录是扁平结构（无进一步嵌套），使目录列举简单直接，无需考虑递归深度问题。

## 为何 JobArchive 完全是本地操作

`JobArchive` 读取 `meta.json` 缓存的 `state` 字段，仅执行本地文件操作。在接受归档请求之前，它**不**发起 `kill -0` 验证远端进程是否真正已死。

这是有意为之的——原因源自**状态缓存设计**（规范 §7.1）：

1. `stopped` 与 `killed` 是**终态**。进程一旦死亡就不会复活。PID 复用理论上可能让新进程继承旧 PID，但面板的 kill 观察机制会跳过终态任务（一旦缓存了 stopped/killed 就不再调用 `kill -0`），从而防止误读存活状态。
2. 由于终态一旦缓存便可靠，对 `stopped` 或 `killed` 任务执行 `JobArchive` 无需远端验证是安全的。
3. 若缓存状态仍为 `running` 或 `kill_failed`，`JobArchive` 会拒绝并返回错误——不是为了"防止归档活着的进程"，而是出于**语义保护**：若缓存状态显示 running，说明 agent 尚未确认任务结束，也尚未查看其结果。未经查看就归档是错误的操作。

正确的 agent 工作流为：`Jobs(name=X)` 刷新状态 → `Read(log_path)` 查看结果 → `JobArchive(name=X)` 归档。无论缓存状态是否陈旧，此流程均可正确运行：
- 若缓存显示 running 但实际已 stopped：`Jobs` 刷新到 stopped；`Read` 显示已完成的输出；`JobArchive` 成功。
- 若确实仍在运行：`Jobs` 确认 running；agent 知道应继续等待。

## 状态缓存的工作机制

`meta.json` 中的 state 字段是面板的核心性能杠杆。它使 `Jobs()` 列表模式无论面板中有多少任务，**至多只需发出一次批量远端 exec**——对终态任务跳过 `kill -0`。

缓存的生命周期：
1. **启动时**：远端进程确认之前，`state` 预置为 `"running"`（启动即为 running，按定义成立）。`pid` 字段在确认后回填。
2. **每次 `Jobs` 或 `JobKill` 观察后**：推导出的状态写回 `meta.json`。后续工具调用无需远端操作即可读到最新值。
3. **终态具有粘性**：一旦写入 `stopped` 或 `killed`，`Jobs` 列表模式便不再观察该任务的 pid。`meta.json` 中的 `kill_attempts` 列表记录 JobKill 尝试的时间线，使 `Jobs(id=N)` 无需远端访问即可重构历史。

权衡：若 MCP 服务器在一次 `Jobs` 调用与一次 `JobKill` 之间崩溃并重启，缓存状态可能落后一个周期。这是可接受的——下次 `Jobs` 调用会纠正，而需要新鲜状态的工具（`JobKill`）始终在其打包 exec 中自行发出 `kill -0`。

## "Archive = 已处理结果"的语义

JobArchive 拒绝归档 `running` 任务是其最不直观的设计选择——这不是为了防止清理活着的进程，而是因为归档意味着"我已处理完这个任务的输出"。

考虑 agent 的心智模型：
- 若缓存 state 为 running，agent（按定义）上次观察到该任务仍在运行。Agent 不可能已经查看了一个它仍认为在运行的任务的输出。
- 未查看输出就归档是数据丢失模式——meta 被移走后，`log_path`、`kill_attempts`、`status_script_output` 等信息的易访问性就丧失了。

通过在 `state ∈ {running, kill_failed}` 时阻止 `JobArchive`，工具强制执行正确的工作流。`running` 保护迫使 agent 先调用 `Jobs`（届时要么确认任务仍在运行，要么将状态更新为 stopped/killed），然后读取日志。

## Zombie 逃生通道

当 `JobKill` 多次尝试（阈值：3 次）后进程仍拒绝退出，agent 有两个选择：
1. 继续尝试不同的信号或运行时特定命令（如 `scancel`、SIGKILL）。
2. 放弃：`JobArchive(name=X, as_zombie=True)`。

`as_zombie=True` 承认"我放弃了；进程继续在远端运行，不再纳入面板管理"。任务被移至 `zombie/` 目录，`zombie=true` 写入其 meta。名称释放供复用。

`zombie/` 目录独立于 `archive/` 的原因是性能：`Jobs(filter='zombies')` 与 zombie 计数阈值检查需要廉价地枚举 zombie——`len(os.listdir("zombie/"))` 是 O(1) 操作，而扫描整个 `archive/` 并过滤 `zombie==true` 是 O(N)。

≥ 5 个 zombie 时触发升级告警，向 agent（最终向用户）发出信号：某个系统性问题正在发生——要么 kill 策略持续错误，要么远端主机存在结构性问题（D 状态进程、root 所有的进程、内核 bug）。该告警仅在触发阈值的 `JobArchive(as_zombie=True)` 调用时触发一次，而非在后续每次工具调用时重复显示，以避免噪音。

## Session ID（sid）与面板持久性

`sid` 通过 `psutil` 从 `PPID + 父进程创建时间 + 主机名` 派生。这一选择具有特定属性：若 MCP 服务器崩溃后被 Claude Code（即 MCP 宿主进程的父进程）重启，新 MCP 服务器看到相同的 PPID 和相同的父进程启动时间——因此派生出相同的 `sid`，面板目录得以保留。

这涵盖了最常见的"面板丢失"场景（长 session 期间 MCP 服务器崩溃或重启），无需 Claude Code 与 MCP 服务器之间进行任何协调。

无法处理的情况：用户完全关闭 Claude Code 后重新打开（或使用 `claude -c` resume 会话）。新的 Claude Code 进程具有新的 PID，因此 MCP 服务器的 PPID 发生变化，`sid` 随之变化，旧面板目录对面板工具不可见。远端任务仍在运行；本地 meta 文件仍存在于旧 `<sid>` 目录下。恢复路径是通过 `Bash("ls ~/.cache/remote-mcp-*-pid")` 枚举所有 session 中各 sid 命名空间下的 pid 文件。

这是 v0.3.0 设计的已知限制。若 Claude Code 未来通过 MCP 初始化握手暴露稳定的 session 标识符，可在后续版本中解决。

## exec_with_snapshot 辅助函数的提取

`exec_with_snapshot(conn, command, timeout) -> ExecResult` 辅助函数从 `_bash_foreground` 提取，使面板工具能够使用相同的快照感知 exec 基础设施，而无需重复超时循环、部分 stdout 收集及 `</dev/null` stdin 设置代码。

所有执行远端命令的面板工具（`Jobs` 观察、`JobKill` 打包 exec、`JobScript` 首次运行、`JobScript` 上传并执行）均通过此辅助函数运行。这确保了以下方面的一致行为：`op_timeout_default` 通道超时、`\r\n` 归一化、通道死亡时的部分输出收集，以及快照 `source` 前导命令。

## 已知限制：面板不跨 Claude Code 重启保留

如 Session ID 部分所述，重启 Claude Code 会产生新的 `sid` 和新的面板目录。这是 v0.3.0 的预期行为。依赖跨 CC 会话长时任务的 agent 应了解以下恢复工作流：

```bash
# 新会话中：查找旧会话遗留的远端任务
Bash("ls ~/.cache/remote-mcp-*-pid 2>/dev/null")

# 检查哪些任务仍存活
Bash("for f in ~/.cache/remote-mcp-*-pid; do pid=$(cat $f); kill -0 $pid 2>/dev/null && echo \"$f: pid=$pid ALIVE\"; done")
```

从旧 pid 文件名可以恢复 `<sid>` 和 `<id>`，进而定位 MCP 宿主机上对应的 `~/.local/share/remote-mcp/jobpane/<old_sid>/` 目录。

## 相关

- 参考文档：[Jobs](../reference/tools/jobs.md)、[JobKill](../reference/tools/job-kill.md)、[JobArchive](../reference/tools/job-archive.md)、[JobScript](../reference/tools/job-script.md)、[Bash](../reference/tools/bash.md)
- 规范 §4（架构总览）、§7（状态机）、§10（JobKill 双层告警）、§11（JobArchive zombie 语义）
