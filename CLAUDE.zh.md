# CLAUDE.md

> English version: [CLAUDE.md](./CLAUDE.md)

本文为 Claude Code (claude.ai/code) 在本仓库中工作时提供指引。

有关按 Diátaxis 框架组织的用户文档（教程 / 操作指南 / 参考 / 说明），见 [`docs/`](./docs/)。本文专为 Claude Code 的视角——表面化负载承载的决策和约定，这些是 agent 修改本代码库前需要了解的。

## 仓库状态

**待实施。** 仓库仅包含设计制品：`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`（v2，权威版本）、先前的 `软件设计文档.md`（v1，已过期）和本 CLAUDE.md。无代码、无 `pyproject.toml`、无测试。新会话通常在此实施设计，而非修改它。**阅读 v2 规范末尾**后再提议架构变更——许多决策（sentinel 协议、重连警告、SFTP-vs-exec 分离、9-tool 表面、MultiRead/FileStat 补充、background-bash via setsid）都有明确的理由，不应在未与用户确认的情况下重新讨论。

## 建设内容

`remote-mcp` 是一个**本地** Python MCP 服务器，向 Claude Code 公开十个工具（Read、Write、Edit、MultiEdit、MultiRead、FileStat、Bash、Glob、Grep、Feedback）。九个在远程 Linux 主机上通过 SSH 运行；第十个（Feedback）写入本地 JSONL 文件以供 agent 驱动的开发循环簿记。七个与 Claude Code 原生工具有对应的（Read/Write/Edit/MultiEdit/Bash/Glob/Grep）与其 schema 和输出格式匹配；MultiRead/FileStat 是带宽驱动的补充，无原生等价物；Feedback 是自我改进通道——agent 提交关于 remote-mcp 本身的 bug/feature 想法，维护者稍后阅读以推动迭代。硬约束：远程主机仅有 SSH（无 agent 安装）、传输是 stdio MCP、SSH 库是 paramiko。

权威设计为 `docs/superpowers/specs/2026-05-26-remote-mcp-design.md`（v2）。仓库根目录的中文版本 `软件设计文档.md` 是先前的 v1 草稿——保留供参考但**被 v2 取代**。

```
Claude Code  ──stdio MCP──▶  remote-mcp (local)  ──SSH/SFTP──▶  remote host
```

每个远程主机一个 MCP 服务器进程，通过 `~/.config/remote-mcp/config.yaml` 中的 `--host <name>` 选择。通过 `claude mcp add` 将每个主机注册为单独条目。

## 架构（负载承载的部分）

设计的正确性取决于三个子系统。搞错这些就一切都白搭。

### 1. 持久 bash 会话 + Sentinel 协议（`bash_session.py`）

Bash 在 SSH 连接的整个生命周期内保活，使得 `cd`、`export` 和 shell 状态在工具调用间持久。因为 stdout 是没有"命令完成"信号的连续流，每次 `execute()` 追加 `echo "RMCP_SENTINEL_<uuid>_EXIT_$?_CWD_$(pwd)"`（sentinel 捕获**exit_code 和 cwd**）并逐行读取 stdout 直到 sentinel 出现。捕获的 cwd 缓存在会话上，Bash 工具用其在结果前缀中显示 `[host=X cwd=Y]` 以获得多主机清晰度。**后台读取线程**必不可少：paramiko 通道缓冲区很小，如果本地端停止消费，远程 bash 会在写入时阻塞并死锁。

生成 `bash --norc --noprofile` 后的初始化序列对于 sentinel 干净解析是不可协商的：`set +m`（无作业控制消息）、`set +o histexpand`（无 `!` 展开）、`export PS1=''`（无提示混入输出）、`export TERM=dumb`、`exec 2>&1`（stderr 合并到 stdout）。超时发送 `\x03`（Ctrl-C）；bash 进程存活以供下一个调用。

### 2. SSH 连接 + SFTP + ProxyJump（`connection.py`）

**进程模型和连接生命周期**（见规范 §5.1.1）：每个注册的 `mcp__remote-<host>__` 是一个**长生命周期操作系统进程**，不是按调用生成的。它在整个 Claude Code 会话期间保活。`main()` 在启动时构建一个 `SSHConnection`，所有工具调用共享它，当 stdio 关闭时在 `finally` 中运行 `conn.close()`。一个 `SSHConnection` per 进程，持有：一个 paramiko `Transport`（带**`compress=True`**——默认开启 SSH 压缩以实现 3-10 倍文本节省）复用一个持久 bash 通道 + 一个懒 SFTP 通道 + 每调用一次的短生命周期 exec 通道。两条执行路径：
- `exec(cmd)` — 无状态，一次性通道。用于 Read（sed-slicing）、Glob、Grep、MultiRead。
- `get_bash_session().execute(cmd)` — 有状态持久 shell。用于 Bash（前台 + 后台启动）。

文件元数据读取（FileStat）通过 SFTP `stat` 进行，**不是** Bash 调用。`transport.set_keepalive(interval)` 必须在 `connect()` 后启用以存活 VPN/防火墙空闲超时（默认 30 s）。ProxyJump 通过在跳转客户端上 `open_channel("direct-tcpip", ...)` 并将结果通道作为 `sock=` 传给目标客户端的 `connect()` 实现。

### 3. 重连检测与显式 agent 警告

SSH 断开时，自动重连一次。bash 会话重新构建**且 shell 状态（cwd、env 变量）消失**。静默恢复被禁止——agent 会继续使用过时的相对路径。`SSHConnection._reconnected` 在成功重连后设为 `True`；`server.py` 中的 `call_tool()` 检查并清除此标志，并在工具结果前缀一个 `[WARNING] SSH connection to <host_name> was lost ...` 解释：(a) 哪个主机重连，(b) cwd 回到 `$HOME` 且 env 为空，(c) 使用绝对路径并重新运行设置。所有四个元素都是必需的（主机名在多主机场景中至关重要——没有它，agent 无法判断哪个主机需要恢复）。如果重连本身失败，返回 `Error: SSH connection to <host> lost and reconnect failed: <reason>` 而不是警告。

## 工具实现约定

- 所有工具返回字符串。**失败返回以 `Error: ...` 开头的字符串**，永不引发异常。Claude Code 根据错误文本自适应。
- 对于 7 个有原生对应物的工具，名称/参数/输出格式必须与 Claude Code 内置的**完全**匹配（例如，Read 返回 `     <lineno>\t<content>`，行号从 1 开始）。错误措词必须逐字——见规范 §6。
- Read 进行远程 `sed -n` slicing，**非** SFTP-整个文件-然后-slice。仅当无 offset/limit 且文件大小 < 1 MB 时回退到 SFTP。
- Write 使用 SFTP 原生递归 mkdir（见 `tools/write.py` 中的 `_sftp_mkdirs`），**不是** `conn.exec("mkdir -p")`。节省通道往返。
- Edit 通过 SFTP 进行读-修改-写，要求 `old_string` 恰好出现一次，对于 0 次匹配 vs. > 1 次匹配返回特定错误（带计数）。对于同一文件上的 > 1 次编辑，使用 MultiEdit。
- MultiEdit 在其编辑列表上是原子的——如果任何编辑失败（0 次匹配或 > 1 次匹配无 `replace_all`），不写入。
- MultiRead 将 N 个文件读取分批为一个 `conn.exec`；块由 `===FILE: <path>===` 标记分隔。
- FileStat 使用 SFTP 的原生 `stat`，**不是** `Bash("stat ...")`——节省通道构建，返回结构化数据。
- Bash 带 `run_in_background=true` 将用户命令包装在 `setsid nohup bash -c '...' > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`。返回 PID + 日志路径 + 4 个准备粘贴的命令模板（status / read output / stop / force-stop）。`setsid` 是**非可选的**——没有它 `kill -- -<pid>` 也会杀死 BashSession。
- Glob 将 `**` 模式转换为 `find -wholename` / `-path` 以保留路径段语义；不仅是 `-name <basename>`（v1 的情形）。
- Grep 支持 `-A/-B/-C` 上下文行、`head_limit`、`output_mode`（content/files_with_matches/count）。带宽赢：agent 可以在一次调用中获取匹配项 + 周围上下文，而不是 grep-然后-多次-读取。
- Feedback 将 JSONL 条目追加到 `~/.local/share/remote-mcp/feedback.jsonl`（路径可通过配置中顶级 `feedback_path` 覆盖）。单个 JSONL 行的 `write()` 对典型大小是 POSIX 原子的——多个 per-host 进程可以安全地写入同一文件。工具本身不传输任何地方；文件是维护者的数据。

## 规划的项目布局

```
remote_mcp/
├── __main__.py        # argparse，然后 asyncio.run(main(...))
├── server.py          # MCP Server，list_tools/call_tool，重连警告分发（含主机名）
├── connection.py      # SSHConnection（compress=True 默认值）、HostConfig、ExecResult、ProxyJump
├── bash_session.py    # BashSession + sentinel 协议（捕获 exit_code 和 cwd）+ 读取线程
└── tools/
    ├── read.py write.py edit.py multi_edit.py multi_read.py file_stat.py bash.py glob.py grep.py feedback.py
CLAUDE.md.fragment.md  # 在仓库根目录发货；用户复制到其远程项目的 CLAUDE.md
```

配置位于 `~/.config/remote-mcp/config.yaml`（可用 `--config` 覆盖）。见规范 §11 了解 schema（hosts、key_path、jump_host、keepalive_interval、compression、bash_timeout_default、glob_output_limit、read_size_cap、bash_output_cap、default_host）。

## 实现顺序

严格的自下而上；规范 §13 中的每阶段验收标准。不要跳过。

1. `connection.py` — exec、SFTP、ProxyJump、keepalive、**compression=True**、重连标志
2. `bash_session.py` — **风险最高的阶段**；在集成前构建独立测试脚本。Sentinel 格式 `RMCP_SENTINEL_<uuid>_EXIT_$?_CWD_$(pwd)` — 一起捕获 exit_code 和 cwd
3. 文件工具：Read（sed-slicing）/ Write（SFTP mkdir）/ Edit / MultiEdit / **MultiRead** / **FileStat**
4. 搜索工具：Glob（`**` via `-wholename`）/ Grep（带 `-A/-B/-C`、`head_limit`、`output_mode`）
5. `server.py` + `__main__.py` + Bash 工具（前台和**`run_in_background`**）+ **Feedback**（本地 JSONL 追加）
6. 打包 + README + `CLAUDE.md.fragment.md`

## 命令（实现后）

```bash
pip install -e .
python -m remote_mcp --host <name> [--config <path>] [--test]
claude mcp add --global remote-<name> -- python -m remote_mcp --host <name>
```

尚无测试运行器、lint 配置或 CI——如需要作为阶段 6 的一部分添加。

## 已知局限性融入设计

不要"修复"这些而未先与用户确认——它们是规范 §14 中的显式范围决策：

- 无交互/TTY 命令（`vim`、`top`、REPLs）。
- Write/Edit/MultiEdit 仅文本/UTF-8；无二进制支持。
- Edit/MultiEdit 非跨进程原子——仅单 agent 串行使用。
- Glob `**` 语义*近似*，非 100% 等价于原生——实现者应运行规范 §13 阶段 4 中的测试用例以捕获分歧。
- Grep `multiline` 参数有意不支持（POSIX grep 限制；agent 应对多行模式使用 `awk`/`perl -0` via Bash）。
- Background bash 日志在 `/tmp/rmcp-bg-*.log` 上不在服务器退出时自动清理（故意——保留以供事后分析；`/tmp` 重启时清理）。
- Background bash PID 重用是已知的低概率风险——agent 在发送 kill 信号前应 `kill -0 <pid>`。
- 跨主机操作（例如从 prod 复制文件到 gpu）**非**一类——完全超出范围。使用 `Bash("scp prod:path gpu:path")`，用户安排 SSH 信任。
- 性能未针对 > 3 个并发主机调优（每个运行自己的 Python 进程）。Federation/plugin 形式是未来工作。
- Feedback 文件不自动轮换；维护者手动存档。无上游遥测——纯本地开发循环。
