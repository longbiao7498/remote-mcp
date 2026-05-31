# 变更日志

> English version: [CHANGELOG.md](./CHANGELOG.md)

所有 remote-mcp 的显著变更均记录于此。格式遵循
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)；版本遵循
[语义化版本](https://semver.org/spec/v2.0.0.html)。

## [0.3.0] — 2026-05-31

### 后台任务面板

v0.3.0 引入了一流的后台任务面板：一个持久的、具名的、可查询的后台任务注册表，用于管理通过 `Bash(run_in_background=True)` 启动的后台任务。Agent 现在可以命名任务、列出状态、挂载状态脚本、kill 任务并归档——无需手写 `pgrep`/`tail`/`kill` 样板代码。设计理念与架构详见 `docs/explanation/job-panel.md`（中文版：`job-panel.zh.md`）。

### 新增——四个面板工具（工具总数 13 → 17）

- **`Jobs(name=X | id=N | filter=F)`** — 查询面板。列表模式返回所有活跃任务及其实时状态；单任务模式额外运行可选的状态脚本。过滤器值：`stopped_unprocessed`（已完成、待查看结果的任务）、`stuck_kill`（经过 ≥ 3 次 kill 仍存活的任务）、`zombies`（已放弃管理并归档为 zombie 的任务）。状态机：`running` / `stopped` / `killed` / `kill_failed`。终态（`stopped`、`killed`）首次确认后不再重新观察，避免 PID 复用产生误判。

- **`JobKill(name=X | id=N [, kill_cmd=...])`** — 在单次打包 exec（5 秒超时）内执行一次 kill 命令并验证进程存活状态。将本次尝试记录至 `kill_attempts[]` 并更新状态。双层升级告警：L1 针对单任务 ≥ 3 次失败；L2 针对本 host ≥ 5 个 stuck 任务。

- **`JobArchive(name=X | id=N [, as_zombie=True])`** — 纯本地操作（零远端调用）。将 `<id>-meta.json`（若有 `<id>-status.sh` 一同迁移）移至 `archive/`（stopped/killed 任务）或 `zombie/`（已放弃管理的 kill_failed 任务）目录。要求 state 为终态；防止归档正在运行或未确认的任务。zombie 数达到 ≥ 5 时触发升级告警。

- **`JobScript(name=X | id=N, script="...", timeout=N)`** — 为任务挂载自定义 bash 状态脚本。脚本本地存储为真相来源，并上传到远端作为缓存；`Jobs(name=X)` 单任务模式自动运行该脚本。挂载时执行首次运行验证：超时则拒绝并清理；非零退出码被接受但附带提示。传入 `script=""` 表示清除。

### 新增——Bash `run_in_background=True` 扩展

- **`log_path`** 参数：为后台任务的 stdout+stderr 指定远端日志路径。默认为 `~/.cache/remote-mcp-<sid>-<id>.log`（与 `/tmp` 不同，跨重启持久）。父目录通过 `mkdir -p` 自动创建。
- **`name`** 参数：供面板引用的人类可读任务别名。在活跃任务中必须唯一。默认为 `bg-<uuid12>`。
- **结构化返回**：后台启动现在返回 `id / name / log_path / pid / started_at`，取代旧的四行提示模板。面板工具替代了原始的 `kill`/`Read` 模板。
- **启动时同步 PID 确认**：若 exec 响应丢失（网络故障），工具立即回退到 SFTP 读取远端 pid 文件。两者均失败时，任务不进入面板，返回明确的 Error 及恢复指引。

### 新增——本地优先的元数据存储

- 面板元数据与状态脚本源文件存储在 MCP host 的本地文件系统 `~/.local/share/remote-mcp/jobpane/<sid>/<host>/` 中。远端只保留扁平命名的文件：`~/.cache/remote-mcp-<sid>-<id>-pid`、`~/.cache/remote-mcp-<sid>-<id>-status.sh` 及日志文件。
- `<sid>` 由 `PPID + 父进程 start_time` 通过 `psutil` 派生，使得同一 Claude Code session 内 MCP server 重启后面板仍然保留。
- ID 为 session+host 范围内通过 `fcntl` flock 分配的单调递增整数；归档后同名任务可以复用同一名称（新旧任务拥有不同 ID）。

### 新增——基础设施

- `exec_with_snapshot(conn, command, timeout) -> ExecResult` 辅助函数从 `_bash_foreground` 提取；所有面板工具与 Bash 共享。
- `remote_mcp/jobs/` 包：`sid.py`、`paths.py`、`init.py`、`meta.py`、`state.py`、`scripts.py`、`constants.py`。
- `RemoteInfo` 输出现在包含 `sid=<value>` 行。
- `BASH_DESC` 已改写，将前台与后台模式实际生成的 shell 命令展开告知 agent。
- 新增依赖 `psutil>=5.9`。

### 已知限制

面板状态不跨 Claude Code 重启保留（新 CC 进程 → 新 PPID → 新 sid → 旧面板目录在新 session 下不可见）。任务仍在远端运行。恢复方式：`Bash("ls ~/.cache/remote-mcp-*-pid")` 可列出所有 session 的远端 pid 文件；通过文件名中的旧 `sid` 值交叉比对。

## [0.2.2] — 2026-05-28

### 网络健壮性——统一行为契约

以下四项修复针对同一根本设计缺陷：早期版本未将网络故障作为一等公民考虑，各工具对其处理方式各行其是。v0.2.2 在框架层建立了三条行为契约（有界时间返回、成功与失败可区分、不虚报结果）。各工具代码基本不变。

### 新增
- `HostConfig.op_timeout_default`（默认 60s）：通过 `channel.settimeout` 将空闲超时应用于所有 SFTP 和 exec 通道。防止笔记本休眠时 SFTP 静默挂起（bug #2）。
- `server.NO_RETRY_TOOLS`（`{Edit, MultiEdit, Bash}`）：该集合中的工具绕过 `_with_retry`，通过新的 `_with_reconnect_only` 辅助函数路由。SSH 故障触发重连，但原始错误返回给 agent——不透明地重新执行。
- 本地内存快照缓存：在 MCP 启动时捕获一次，持久化到远端 `~/.cache/remote-mcp/snapshot-<pid>.sh`。重连时仅在远端文件缺失的情况下从缓存重新上传；永不重新运行 `bash -ic`（会话中途的 bashrc 变更故意不被感知，与 Claude Code 原生行为一致）。
- 后台 bash pidfile：`_bash_background` 在 echo `BG_PID` 之前将 PID 写入 `/tmp/rmcp-bg-<uuid>.pid`。即使 echo 响应丢失，agent 也可以通过 `Bash("cat /tmp/rmcp-bg-*.pid")` 恢复孤儿 PID（bug #3）。

### 变更
- Edit 和 MultiEdit 在 SSH 层故障时不再自动重试（bug #1）。读-改-写工具若已在远端成功写入，重试后可能返回虚假的 `old_string not found`。agent 现在看到 `Error: <SSHException>: ...`，自行决定是否重新发起。
- Bash 的 SSH 层故障同样不再经过 `_with_retry`（v0.2.1 中的 Bash 通道死亡处理逻辑不变）。
- 重连 WARNING 文本现有三种变体：(A) 正常复用，不提及快照；(B) "远端快照缺失，已从本地缓存重新上传"；(C) "重新上传失败，后续 Bash 将在无 PATH/别名的环境下运行"（bug #4）。
- 新增"会话启动时快照捕获失败"WARNING，在初始快照捕获失败后首次工具调用时显示一次。
- 快照文件位置从 `/tmp/rmcp-snapshot-<host>-<pid>.sh` 迁移到 `~/.cache/remote-mcp/snapshot-<pid>.sh`，避免 `/tmp` 被清理。
- `close()` 不再删除远端快照文件（它持久保存在 `~/.cache/` 中）。
- `connect()` 不再调用快照捕获；捕获现在由 `server.main()` 在启动时触发一次。

## [0.2.1] — 2026-05-28

### 修复
- **Bash 通道死亡现在能明确暴露**，不再返回模糊的 `[Exit code: -1]`。当 SSH transport 在命令执行中途断开（如笔记本休眠、网络抖动），`Bash` 现在返回 `Error: SSH channel to <host> closed unexpectedly during command (transport likely disconnected ...). The next tool call will trigger reconnect. Re-run this command only if it is safe to repeat.`。下一次工具调用会触发正常的 `_with_retry` 重连机制。**故意不自动重跑**该命令——是否重跑由 agent 判断（`rm`、`migrate` 等非幂等命令静默重跑会有害）。
- **Drain 循环异常范围收窄**：`_bash_foreground` 轮询循环现在只 catch `socket.timeout`（`channel.settimeout` 的正常轮询信号），而非笼统的 `Exception`。防御性改动：避免未来 paramiko 版本变化时意外吞掉 dead channel 抛出的 `socket.error` / `EOFError` / `SSHException`。

## [0.2.0] — 2026-05-27

### 破坏性变更
- **非持久化 Bash**：shell 状态（cwd、环境变量、已 source 的 venv）不再跨 Bash 调用持久。请使用 `cd dir && cmd`、`FOO=bar cmd`、`venv/bin/python script.py` 的方式在行内传递状态。与 Claude Code 原生行为对齐。
- **输出格式**：所有工具的输出现在以 `\n\n[host=X cwd=Y]` 结尾（v0.1.x 中仅 Bash 在输出前加 `[host=X cwd=Y]\n` 前缀；现在由 MCP server 统一作为后缀附加）。解析精确字节偏移的脚本需要更新。
- **Glob/Grep 输出路径**：默认 `path="."` 现在解析为配置的 cwd → 输出绝对路径（`/opt/app/foo.py`），而非相对路径（`./foo.py`）。与 Claude Code 原生行为对齐。

### 新增
- `--cwd <path>` CLI 标志与 `hosts.<name>.cwd` YAML 字段——为所有工具的相对路径提供锚点（`Read("config.yaml")` → `<cwd>/config.yaml`）。默认值 = 远程 `$HOME`。格式须为 `/...`、`~` 或 `~/...`；格式不合法则在启动时快速失败。波浪号在连接时展开。通过 SFTP stat 验证路径存在性——cwd 不存在则 MCP server 拒绝启动。
- `remote_mcp/paths.py`，含 `resolve_path(path, cwd)` 辅助函数。
- `RemoteInfo` 输出现在包含 `cwd=<value>` 行。

### 移除
- `remote_mcp/bash_session.py`（持久化 shell + sentinel 协议——已由按次调用 exec + 快照回放取代）。
- `SSHConnection.get_bash_session()`。

### 变更
- 重连 WARNING 简化为：`[WARNING] SSH connection to <host> was lost and has been re-established. Snapshot was rebuilt; if your bashrc has changed since the connection started, the new state takes effect from this point.`
- Bash 超时现在使用 `channel.close()`（通过 channel 关闭发送 SIGHUP），而非通过 PTY 发送 Ctrl-C。超时前收集到的部分 stdout 会包含在错误输出中。

## [0.1.1] - 未发布

### 变更

由 agent 反馈驱动（`Feedback` 工具首次真实使用 —— 见 `~/.local/share/remote-mcp/feedback.jsonl`）：

- **Grep 默认跳过二进制文件**。给常驻 grep 标志加了 `-I`。以前 ELF 可执行文件、vim swap 文件、归档等的匹配会污染输出，现在静默排除。与原生 Claude Code Grep（使用 ripgrep）行为一致。**未引入新参数**——如确实需要搜索二进制内容，直接用 Bash。*Agent 在 `tjcs_ln5` 主机上看到 `printf` 在 ELF 二进制和 `.swp` 文件中匹配后报告。*

- **Edit 和 MultiEdit 的 `found N times` 错误现在列出匹配行号**。原文：`Error: old_string found 3 times in <path>. Provide more context to match uniquely, or set replace_all=true to replace all.` 现在：`Error: old_string found 3 times in <path> (lines 19, 20, 21). Provide more context to match uniquely, or set replace_all=true to replace all.` 行号列表上限 10 个，超出加后缀 `..., ... +K more`。agent 想做唯一替换时省一次 Grep 跟进。同样的改进也应用到 MultiEdit 的 per-edit 错误。*同一测试会话中 agent 建议。*

### 新增 — 三个新工具（工具总数 10 → 13）

- **`Upload(local_path, remote_path)`** —— 通过 SFTP 把本地文件推到远程。二进制安全。前置检查：存在性、类型（必须是文件）、大小（必须 ≤ `transfer_size_cap`）。远程父目录自动创建。Linux/macOS 上，工具描述与超大文件错误都引导 agent 改用 `Bash("scp ...", run_in_background=true)`——非阻塞、不限大小、可恢复。Upload 是 Windows-无-scp 的兜底。

- **`Download(remote_path, local_path)`** —— 通过 SFTP 把远程文件拉到本地。与 Upload 对称（同 cap、同 scp 引导）。传输前用 SFTP `stat` 检查远程存在性和大小。本地父目录必须已存在（不自动创建——与 Upload 不对称）。

- **`RemoteInfo()`** —— 返回连接的已配置身份，5 行 `key=value`（`host`、`user`、`hostname`、`port`、`jump_host`）。**不发 SSH 请求**——读 `conn.config`。VPN 安全：VPN 场景下远程 `hostname -I` 返回内网 IP，与客户端连接的 IP 不一致；本工具返回后者。

### 新增 — 配置

- `HostConfig.transfer_size_cap` —— int，默认 `100 * 1024 * 1024`（100 MB）。`Upload` / `Download` 单文件大小上限。超出返回 `Error: ...`，并附上可直接粘贴的 `Bash + scp` 命令。

### 变更 — 引导

- `CLAUDE.md.fragment.md`：新增规则，引导 agent 在 Linux/macOS 上优先用 `Bash + scp` 做传输；Upload/Download 明确定位为 Windows 兜底。

### 说明

发布前文档里发现的同类 bug 也记录在此供存档：写文档过程中我错误地编造了几个外部工具的具体细节（`--global` 标志、`/tools` 斜杠命令、`~/.claude/logs/` 日志路径、虚构的多行 `--test` 输出）。全部由专家审查发现并修正；修正与本次 `[0.1.1]` 同窗口入库。教训写入项目今后的文档撰写规范：任何关于外部工具的 CLI / 路径 / 输出格式声明，必须通过运行命令、读源码或查官方文档来验证——不能凭印象编。

## [0.1.0] - 2026-05-26

初始发布。完整实现 v2 设计规范。

### 新增

**十个 MCP 工具**通过 stdio 公开，所有在远程 Linux 主机上通过 SSH 运行：

- `Read` — 读取远程文件（服务器端 `sed` slicing；仅请求的行穿过网络）
- `Write` — 写入文件（SFTP 原生递归 `mkdir`）
- `Edit` — 唯一性检查的单字符串替换
- `MultiEdit` — 单个文件上的原子多编辑（任意数量编辑的 1 次读取 + 1 次写入）
- `MultiRead` — 一次往返中批量读取 N 个文件
- `FileStat` — 元数据查询（存在、大小、mtime），无需传输文件内容
- `Bash` — 持久 shell，前缀 `[host=X cwd=Y]`；`run_in_background=true` 返回 PID + 日志路径以供清洁进程组 kill（`setsid` 包装）
- `Glob` — `find` 支持的模式搜索；`**` 通过 `-wholename` 近似
- `Grep` — 上下文行（`-A`/`-B`/`-C`）、`head_limit`、`output_mode`（content / files_with_matches / count）
- `Feedback` — 本地 JSONL 追加供 agent 提交的开发循环备注（bugs / enhancements）

**连接基础设施**：
- 每个 MCP 服务器进程一个 paramiko Transport（compress=on，keepalive=30s）
- 复用通道：持久 bash + 懒 SFTP + 短生命周期 exec
- SSH 断开时自动重连一次；后续工具调用前缀为 `[WARNING] SSH connection to <host> was lost ...`
- 可选 ProxyJump via `open_channel("direct-tcpip", ...)`

**Bash 会话**：
- Sentinel 协议在一次往返中捕获 exit 代码和 `pwd`
- PTY 分配使 `\x03`（Ctrl-C）实际传递 SIGINT 到前台进程——实现超时而不杀死会话
- 后台读取线程（必需；防止远程 bash 在缓冲区满时阻塞）

**CLI**：
- `python -m remote_mcp --host <name>`（stdio MCP 循环）
- `--config <path>`（默认 `~/.config/remote-mcp/config.yaml`）
- `--test`（烟雾测试可达性，退出）

### 已知局限性

见规范 §14。要点：
- 无交互/TTY 命令（vim、top、REPLs）
- Write/Edit/MultiEdit 仅文本/UTF-8
- Glob `**` 近似，非 100% 等价于原生
- Grep `multiline` 有意不支持（POSIX grep 限制）
- ProxyJump 集成测试在开发主机上跳过（AllowUsers ACL 阻止自跳转）；代码正确，只是未端到端测试
- 跨主机操作非一类——使用 `Bash("scp host_a:p host_b:p")`

### 未实现

见规范 §15 了解未来工作——主要包括：
- Claude Code 插件形式（会自动安装 M2 工作流指南作为始终开启的技能并公开 `/remote-add`、`/remote-cd` 等）
- 文件 > 100 MB 的读取流
- Background Bash 日志自动轮换

[0.1.0]: https://github.com/longbiao7498/remote-mcp/releases/tag/v0.1.0
