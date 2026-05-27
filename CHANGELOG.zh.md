# 变更日志

> English version: [CHANGELOG.md](./CHANGELOG.md)

所有 remote-mcp 的显著变更均记录于此。格式遵循
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)；版本遵循
[语义化版本](https://semver.org/spec/v2.0.0.html)。

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
