# 变更日志

> English version: [CHANGELOG.md](./CHANGELOG.md)

所有 remote-mcp 的显著变更均记录于此。格式遵循
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)；版本遵循
[语义化版本](https://semver.org/spec/v2.0.0.html)。

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
