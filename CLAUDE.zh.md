# CLAUDE.md

> English version: [CLAUDE.md](./CLAUDE.md)

本文为 Claude Code (claude.ai/code) 在本仓库中工作时提供指引。

有关按 Diátaxis 框架组织的用户文档（教程 / 操作指南 / 参考 / 说明），见 [`docs/`](./docs/)。本文专为 Claude Code 的视角——表面化负载承载的决策和约定，这些是 agent 修改本代码库前需要了解的。

## 仓库状态

**v0.2.0 已实施。** A–C 阶段（非持久 Bash、可配置 cwd、统一输出后缀）已完成。权威设计为 `docs/superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md`（v0.2.0 规范，v2 的增量）。v2 规范 `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` 对未被 v0.2.0 规范覆盖的内容仍保持权威。在本仓库工作的新会话：提议架构变更前**请通读两份规范**——许多决策（snapshot 机制、cwd 策略、`~` 两层语义、统一后缀、SFTP-vs-exec 分离、工具表面、background-bash via setsid）都有明确的理由，不应在未与用户确认的情况下重新讨论。

## 建设内容

`remote-mcp` 是一个**本地** Python MCP 服务器，向 Claude Code 公开十个工具（Read、Write、Edit、MultiEdit、MultiRead、FileStat、Bash、Glob、Grep、Feedback）。九个在远程 Linux 主机上通过 SSH 运行；第十个（Feedback）写入本地 JSONL 文件以供 agent 驱动的开发循环簿记。七个与 Claude Code 原生工具有对应的（Read/Write/Edit/MultiEdit/Bash/Glob/Grep）与其 schema 和输出格式匹配；MultiRead/FileStat 是带宽驱动的补充，无原生等价物；Feedback 是自我改进通道——agent 提交关于 remote-mcp 本身的 bug/feature 想法，维护者稍后阅读以推动迭代。硬约束：远程主机仅有 SSH（无 agent 安装）、传输是 stdio MCP、SSH 库是 paramiko。

权威设计为 `docs/superpowers/specs/2026-05-26-remote-mcp-design.md`（v2，基础）和 `docs/superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md`（v0.2.0 增量）。仓库根目录的中文版本 `软件设计文档.md` 是先前的 v1 草稿——保留供参考但**被 v2 取代**。

```
Claude Code  ──stdio MCP──▶  remote-mcp (local)  ──SSH/SFTP──▶  remote host
```

每个远程主机一个 MCP 服务器进程，通过 `~/.config/remote-mcp/config.yaml` 中的 `--host <name>` 选择。通过 `claude mcp add` 将每个主机注册为单独条目。

## 架构（负载承载的部分）

设计的正确性取决于以下子系统。搞错这些就一切都白搭。

### 1. 非持久 Bash + Snapshot 回放（`tools/bash.py` + `connection.py::_create_snapshot`）

每次 Bash 调用都是一个全新的 `bash --noprofile --norc -c "source /tmp/rmcp-snapshot-<host>-<pid>.sh 2>/dev/null || true; <cmd>" </dev/null`。Snapshot 在 SSH 连接建立后一次性创建，使用 `bash -ic 'declare -p; declare -fp; alias'`，并在末尾追加 `cd <configured-cwd> || exit 1`，使每次 Bash 调用都从配置的 cwd 开始。**行为与 Claude Code 原生 Bash 对齐**：shell 状态（cwd、env、已 source 的 venv）跨调用不持久。需要链式状态的 agent 必须在单次调用内完成：`cd dir && cmd`、`VAR=v cmd`、`venv/bin/python script.py`。

stdin 重定向 `</dev/null` 是不可协商的——它让 `srun`、`cat`（无参数）等读 stdin 的命令立即返回而不是挂起。超时使用 `channel.close()`（通过 SSH session 关闭发送 SIGHUP）；不分配 PTY。

### 2. 可配置 cwd + 路径解析（`paths.py` + `connection.py::_resolve_and_validate_cwd`）

`--cwd /opt/app`（CLI）或 `hosts.<name>.cwd`（YAML）为所有相对路径提供锚点。格式必须为 `/...`、`~` 或 `~/...`。`~` 在连接时通过 `bash -c 'echo $HOME'` 一次性展开，结果写回 `self.config.cwd`（使 RemoteInfo / 后缀 / snapshot 都显示同一个绝对路径）。SFTP `stat` 在启动时校验存在性（fail-fast——cwd 不存在则 MCP server 拒绝启动）。未配置时默认等价于 `cwd: ~`。

所有非 Bash 工具调用 `paths.resolve_path(path, conn.config.cwd)`：
- 绝对路径 → 原样返回
- 相对路径 → `posixpath.normpath(posixpath.join(cwd, path))`
- 空路径 → `ValueError("empty path")`
- `~` 前缀 → `ValueError("path starts with '~'...")`

Bash 的 cwd 通过写入 snapshot 的 `cd` 行设置，而非 `resolve_path`（agent 的 `command` 字符串可能在 shell 表达式中引用路径，我们不解析它）。

### 3. SSH 连接 + SFTP + ProxyJump（`connection.py`）

**进程模型和连接生命周期**：每个注册的 `mcp__remote-<host>__` 是一个**长生命周期操作系统进程**，不是按调用生成的。它在整个 Claude Code 会话期间保活。`main()` 在启动时构建一个 `SSHConnection`，所有工具调用共享它，当 stdio 关闭时在 `finally` 中运行 `conn.close()`。一个 `SSHConnection` per 进程，持有：一个 paramiko `Transport`（带**`compress=True`**——默认开启 SSH 压缩以实现 3-10 倍文本节省）支持一个懒 SFTP 通道 + 每调用一次的短生命周期 exec 通道。所有工具调用（包括 Bash）都使用 `exec(cmd)`——无状态、一次性通道。

文件元数据读取（FileStat）通过 SFTP `stat` 进行，**不是** Bash 调用。`transport.set_keepalive(interval)` 必须在 `connect()` 后启用以存活 VPN/防火墙空闲超时（默认 30 s）。ProxyJump 通过在跳转客户端上 `open_channel("direct-tcpip", ...)` 并将结果通道作为 `sock=` 传给目标客户端的 `connect()` 实现。

### 4. 统一输出后缀（`server.py::call_tool`）

`server.py::call_tool()` 在所有工具结果末尾追加 `\n\n[host=X cwd=Y]`。**工具自身不得在结果前面拼接 host/cwd 前缀**（旧的 `tools/bash.py:59` 风格已删除）。错误结果同样带后缀——agent 看到 `Error: File not found: foo.txt\n\n[host=prod cwd=/opt/app]` 可一眼判断是哪台主机哪个目录出的问题。

### 5. 重连检测与显式 agent 警告

SSH 断开时自动重连一次，重连后重建 snapshot。静默恢复被禁止——agent 需要知道连接曾中断。`SSHConnection._reconnected` 在成功重连后设为 `True`；`server.py` 中的 `call_tool()` 检查并清除此标志，并在工具结果前追加 `[WARNING] SSH connection to <host_name> was lost and has been re-established. Snapshot was rebuilt; if your bashrc has changed since the connection started, the new state takes effect from this point.`。主机名在多主机场景中至关重要。如果重连本身失败，返回 `Error: SSH connection to <host> lost and reconnect failed: <reason>` 而不是警告。

## 工具实现约定

- 所有工具返回字符串。**失败返回以 `Error: ...` 开头的字符串**，永不引发异常。Claude Code 根据错误文本自适应。
- 对于 7 个有原生对应物的工具，名称/参数/输出格式必须与 Claude Code 内置的**完全**匹配（例如，Read 返回 `     <lineno>\t<content>`，行号从 1 开始）。错误措词必须逐字——见规范 §6。
- Read 进行远程 `sed -n` slicing，**非** SFTP-整个文件-然后-slice。仅当无 offset/limit 且文件大小 < 1 MB 时回退到 SFTP。
- Write 使用 SFTP 原生递归 mkdir（见 `tools/write.py` 中的 `_sftp_mkdirs`），**不是** `conn.exec("mkdir -p")`。节省通道往返。
- Edit 通过 SFTP 进行读-修改-写，要求 `old_string` 恰好出现一次，对于 0 次匹配 vs. > 1 次匹配返回特定错误（带计数）。对于同一文件上的 > 1 次编辑，使用 MultiEdit。
- MultiEdit 在其编辑列表上是原子的——如果任何编辑失败（0 次匹配或 > 1 次匹配无 `replace_all`），不写入。
- MultiRead 将 N 个文件读取分批为一个 `conn.exec`；块由 `===FILE: <path>===` 标记分隔。
- FileStat 使用 SFTP 的原生 `stat`，**不是** `Bash("stat ...")`——节省通道构建，返回结构化数据。
- Bash 带 `run_in_background=true` 将用户命令包装在 `setsid nohup bash -c '...' > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`。返回 PID + 日志路径 + 4 个准备粘贴的命令模板（status / read output / stop / force-stop）。`setsid` 是**非可选的**——它使后台进程脱离 exec 通道的 session，确保通道关闭（超时/重连）不会杀死后台进程。
- Glob 将 `**` 模式转换为 `find -wholename` / `-path` 以保留路径段语义；不仅是 `-name <basename>`（v1 的情形）。
- Grep 支持 `-A/-B/-C` 上下文行、`head_limit`、`output_mode`（content/files_with_matches/count）。带宽赢：agent 可以在一次调用中获取匹配项 + 周围上下文，而不是 grep-然后-多次-读取。
- Feedback 将 JSONL 条目追加到 `~/.local/share/remote-mcp/feedback.jsonl`（路径可通过配置中顶级 `feedback_path` 覆盖）。单个 JSONL 行的 `write()` 对典型大小是 POSIX 原子的——多个 per-host 进程可以安全地写入同一文件。工具本身不传输任何地方；文件是维护者的数据。

## 项目布局

```
remote_mcp/
├── __main__.py        # argparse（--host、--cwd、--config），然后 asyncio.run(main(...))
├── server.py          # MCP Server，list_tools/call_tool，统一后缀 + 重连警告分发
├── connection.py      # SSHConnection（compress=True、snapshot 管理、cwd 校验）、HostConfig、ProxyJump
├── paths.py           # resolve_path(path, cwd) helper，供所有非 Bash 工具使用
└── tools/
    ├── read.py write.py edit.py multi_edit.py multi_read.py file_stat.py bash.py glob.py grep.py feedback.py
CLAUDE.md.fragment.md  # 在仓库根目录发货；用户复制到**本地**项目的 CLAUDE.md（Claude Code 启动时读的那个文件——**不是**远程主机上的文件）
```

`bash_session.py` **不存在**——在 v0.2.0 中已删除。不再有持久 bash 会话、sentinel 协议或读取线程。

配置位于 `~/.config/remote-mcp/config.yaml`（可用 `--config` 覆盖）。见规范 §11 了解 schema（hosts、key_path、jump_host、keepalive_interval、compression、bash_timeout_default、glob_output_limit、read_size_cap、bash_output_cap、default_host）。

## 实现顺序（v0.2.0 已完成）

自下而上完成；每阶段验收标准见 v0.2.0 规范 §11。

1. `connection.py` — exec、SFTP、ProxyJump、keepalive、**compression=True**、重连标志、snapshot 管理、cwd 校验
2. `paths.py` — `resolve_path()` helper
3. 文件工具：Read（sed-slicing）/ Write（SFTP mkdir）/ Edit / MultiEdit / **MultiRead** / **FileStat** — 均集成 `resolve_path`
4. 搜索工具：Glob（`**` via `-wholename`）/ Grep（带 `-A/-B/-C`、`head_limit`、`output_mode`）— 均集成 `resolve_path`
5. `server.py` + `__main__.py`（`--cwd`）+ Bash 工具（per-call exec + snapshot 包装，前台和**`run_in_background`**）+ **Feedback**（本地 JSONL 追加）+ `call_tool()` 统一后缀
6. 打包 + README + `CLAUDE.md.fragment.md`

## 命令

```bash
pip install -e .
python -m remote_mcp --host <name> [--cwd /opt/app] [--config <path>] [--test]
claude mcp add --scope user remote-<name> -- python -m remote_mcp --host <name> --cwd /opt/app
```

`--cwd` 是可选的（默认为远程用户 `$HOME`）。它为所有工具的相对路径提供锚点，并设置每次 Bash 调用的起始目录。

## 已知局限性融入设计

不要"修复"这些而未先与用户确认——它们是显式的范围决策：

- 无交互/TTY 命令（`vim`、`top`、REPLs）。
- Write/Edit/MultiEdit 仅文本/UTF-8；无二进制支持。
- Edit/MultiEdit 非跨进程原子——仅单 agent 串行使用。
- Glob `**` 语义*近似*，非 100% 等价于原生——应运行 v0.2.0 规范 §11 中的测试用例以捕获分歧。
- Grep `multiline` 参数有意不支持（POSIX grep 限制；agent 应对多行模式使用 `awk`/`perl -0` via Bash）。
- Bash shell 状态（cwd、env 变量、已激活的 venv）跨调用不持久——这是与 Claude Code 原生 Bash 对齐的设计决策。链式命令请内联完成：`cd dir && cmd`、`VAR=val cmd`、`venv/bin/python script.py`。
- 每次 Bash 调用需承担新 bash 进程启动开销（~50-1000ms，取决于 RTT 和远程文件系统速度）。这是与原生行为对齐的已接受代价。可通过 `&&` 合并相关命令减少调用次数。
- Background bash 日志在 `/tmp/rmcp-bg-*.log` 上不在服务器退出时自动清理（故意——保留以供事后分析；`/tmp` 重启时清理）。
- Background bash PID 重用是已知的低概率风险——agent 在发送 kill 信号前应 `kill -0 <pid>`。
- 工具路径参数中的 `~` 被明确拒绝——请使用绝对路径或相对配置 cwd 的路径。
- cwd 不做沙箱限制——`../` 可以逃出配置的 cwd（与 CC 原生策略一致；安全边界在 SSH 用户权限层）。
- 跨主机操作（例如从 prod 复制文件到 gpu）**非**一类——完全超出范围。使用 `Bash("scp prod:path gpu:path")`，用户安排 SSH 信任。
- 性能未针对 > 3 个并发主机调优（每个运行自己的 Python 进程）。Federation/plugin 形式是未来工作。
- Feedback 文件不自动轮换；维护者手动存档。无上游遥测——纯本地开发循环。
