# 架构概览

> English version: [architecture.md](./architecture.md)

本文档建立你理解 remote-mcp 所需的心智模型：有哪些进程、哪些协议将它们连接起来、数据如何流转，以及为何这种分层结构是这样设计的。在深入研究任何单独模块之前，请先阅读本文——一旦你看清整体拓扑，这套设计就会清晰得多。

## 根本出发点

remote-mcp 的存在是为了解决一个看似简单、却有着出乎意料丰富解法空间的问题：Claude Code 内置的文件系统和 shell 工具在本地机器上运行，但你想要操作的文件和进程却存在于一台只能通过 SSH 访问的远程 Linux 服务器上。

最朴素的答案——「直接 SSH 进去执行命令」——忽略了一个事实：Claude Code 不是一个 shell，它是一个 agent，以结构化工具调用的方式发出请求、接收有类型的响应。真正的挑战在于：让远程主机的文件系统和 shell，在 Claude Code 眼中，与本地资源无从区分。

## 进程拓扑

```
┌──────────────────────────────────────────────────────────────┐
│                         Local machine                        │
│                                                              │
│  ┌──────────────┐    stdio MCP     ┌──────────────────────┐  │
│  │  Claude Code │ ◄──────────────► │     remote-mcp       │  │
│  │              │   (JSON-RPC 2.0) │  (one OS process     │  │
│  └──────────────┘                  │   per remote host)   │  │
│                                    └──────────┬───────────┘  │
└───────────────────────────────────────────────│──────────────┘
                                                │
                              SSH (compress=on, keepalive=30s)
                              one persistent TCP connection
                                                │
                    ┌───────────────────────────▼──────────────┐
                    │              Remote Linux host            │
                    │                                          │
                    │   ┌──────────────────────────────────┐   │
                    │   │  bash --norc (persistent session) │   │
                    │   └──────────────────────────────────┘   │
                    │   Native filesystem (via SFTP)           │
                    │   Ephemeral exec channels (Glob, Grep)   │
                    └──────────────────────────────────────────┘
```

这里有两条关键边界：Claude Code 与 remote-mcp 之间的 stdio MCP 边界，以及 remote-mcp 与远程主机之间的 SSH 边界。所有有趣的事情，都发生在夹在两者之间的 remote-mcp 进程里。

## 每主机进程模型

每台远程主机拥有自己独立的 remote-mcp 操作系统进程。这不是一个管理多个连接的守护进程——它是单一用途的中继器，一台主机对应一个进程。Claude Code 启动时会派生这个进程，进程在整个 Claude Code 会话期间持续存活。当 Claude Code 关闭时，stdio 管道收到 EOF，进程的 `try/finally` 触发，SSH 连接被干净地拆除。

注册命令如下：

```bash
claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
claude mcp add --scope user remote-gpu  -- python -m remote_mcp --host gpu
```

两台主机，两个进程，两条 SSH 连接。它们在运行时不共享任何东西。Claude Code 看到的工具名称是 `mcp__remote-prod__Read`、`mcp__remote-gpu__Bash` 等等——MCP 命名空间前缀让每一次工具调用都清楚地携带了主机标识。

这是一个刻意保持简单的模型。关于其局限性以及为何联邦备选方案被拒绝，请参阅[多主机模型](./multi-host-model.md)。

## SSH Transport 及其通道

在 remote-mcp 进程内部，单个 paramiko `Transport` 位于核心位置。Transport 是一条已升级为 SSH 会话状态的持久 TCP 连接——主机密钥验证完成、加密协商完毕、认证通过。所有后续通信都流经这条 TCP 连接，复用在多个 SSH 通道上。

各通道类型及其生命周期：

```
┌─────────────────────────────────────────────────────────────────┐
│  remote-mcp OS process  (lives for the entire Claude Code session)
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  paramiko Transport  (one persistent TCP + SSH session)  │   │
│  │                                                          │   │
│  │  ┌────────────────┐  ┌─────────────────┐  ┌──────────┐  │   │
│  │  │  bash channel  │  │   SFTP client   │  │ exec ×N  │  │   │
│  │  │  (persistent,  │  │  (lazy-init,    │  │ (short-  │  │   │
│  │  │  lives with    │  │  reused for all │  │ lived,   │  │   │
│  │  │  Transport)    │  │  file ops)      │  │ per call)│  │   │
│  │  └────────────────┘  └─────────────────┘  └──────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  disconnect / reconnect → entire Transport subtree is rebuilt   │
└─────────────────────────────────────────────────────────────────┘
```

### 持久 bash 通道

远程主机上运行一个 bash 进程，其生命周期与 Transport 相同。它以 `bash --norc --noprofile` 启动（不加载启动文件，状态干净），并通过一系列强制初始化序列禁用了作业控制通知、提示字符串、历史扩展以及终端控制序列——所有这些都会污染输出流。

正是这个通道赋予了 Bash 工具有状态的特性：`cd` 命令、`export` 声明和 source 的文件都会跨工具调用持续存在，因为它们都在同一个 bash 进程内执行。

判断命令何时完成的协议并不简单。sentinel 协议的设计理由，请参阅[设计决策](./design-decisions.md)；精确的实现机制，请参阅 `bash_session.py` 模块参考。

### SFTP 客户端

SFTP 在第一次文件操作时懒初始化，此后复用。它专门用于文件读、写和编辑操作。选择 SFTP 而非 shell 命令来进行文件 I/O 是经过深思熟虑的：SFTP 是二进制安全的，无需 shell 转义，并且复用了已打开的通道。一个包含单引号、美元符号或换行符的文件，无需任何特殊处理即可正确传输。

Write 工具利用 SFTP 自身的 mkdir 能力来创建父目录，避免了额外的 exec 通道往返。

### 临时 exec 通道

Glob 和 Grep 使用 `SSHConnection.exec()`，它会打开一个新通道、运行命令、读取结果，然后关闭通道。这些工具本质上是无状态的——grep 调用没有「当前目录」的概念。exec 模型正是合适的选择：简单、隔离、无共享状态可能被破坏。

Read 工具的远端 `sed` 切片以及 MultiRead 构造的多文件脚本，也都使用 exec 通道。

## 两条执行路径

每次工具调用最终走向两条路径之一：

**无状态 exec 路径**（Glob、Grep、Read、MultiRead、Write 的 mkdir）：`SSHConnection.exec(command)` 打开通道、运行命令、返回 stdout + stderr + 退出码，然后关闭通道。无共享状态，无持久性，无顺序约束。

**有状态 bash 路径**（Bash 工具）：`conn.get_bash_session().execute(command)` 通过 stdin 将命令发送到持久 bash 进程，等待输出流中的 sentinel，然后返回收集到的输出。shell 状态（当前目录、环境变量、已 source 的文件）随调用累积。

这种分离是举足轻重的。如果一切都走 exec，就会丢失 shell 状态。如果一切都走 bash 会话，则需要仔细转义，更难并行化（bash 通道是单一队列），Glob 和 Grep 的语义也会更加脆弱。

## 文件操作：仅用 SFTP

Read（完整文件路径，非 sed 切片路径）、Write、Edit、MultiEdit、MultiRead 和 FileStat 的实际文件传输都使用 SFTP。SFTP 操作在持久 SFTP 通道上运行，无需打开新的 exec 通道。文件相关工具中出现 exec 通道的唯一原因，是 Read 和 MultiRead 中的 `sed` 切片——实际数据通过 exec 结果返回，而非 SFTP。

FileStat 值得特别一提：它使用 SFTP 的 `stat()` 调用，以几个字节返回结构化的元数据（大小、mtime、权限、类型）。对于「这个文件存在吗，有多大？」这类问题，它才是正确的工具——而不是 Read，因为 Read 会传输整个文件。

## Keepalive 与连接稳定性

`transport.set_keepalive(30)` 每 30 秒在 SSH 协议层发送一次心跳。这很重要，因为 remote-mcp 进程在工具调用之间可能空闲数分钟，而许多 VPN 和防火墙会静默地断开看似空闲的 TCP 连接。keepalive 防止了这种情况，对工具调用没有任何可见影响。

当连接确实断开时，重连行为涉及重建整个 Transport 子树——新的 TCP 连接、新的认证、新的 bash 进程、新的 SFTP 客户端。这对 agent 意味着什么，请参阅[重连与 WARNING 协议](./reconnect-and-warning.md)。

## ProxyJump

对于只能通过跳板机访问的主机，remote-mcp 使用 paramiko 的通道 API 实现 ProxyJump：在跳板机 Transport 上打开一个 `direct-tcpip` 通道（提供通往目标机器的类 TCP 流），然后将该通道作为 `sock=` 参数传递给目标主机的 `connect()`。从目标机器的角度看，结果是一条正常的入站连接，但其字节物理上经由跳板机传输。

跳板机在 `config.yaml` 中配置为 `jump_host: <name>`，引用同一 hosts 映射中的另一个条目。

## SSH 压缩

所有 SSH 流量均以 `compress=True` 发送，在传输前通过 zlib 压缩。

源代码、配置文件和日志输出具有极高的可压缩性——ASCII 文本通常能达到 3–10 倍的压缩比。这意味着一个 100 KB 的 Python 文件，传输时可能只有 15–30 KB 的压缩 SSH 负载。压缩在 paramiko 层透明发生，工具层的任何代码都无需感知它。

关于这套设计如何应对受限网络条件的完整图景，请参阅[带宽与延迟](./bandwidth-and-latency.md)。

## 各工具的位置

| 工具 | 通道类型 | 有状态性 |
|------|-------------|--------------|
| Read (sed path) | exec | stateless |
| Write | SFTP (mkdir via exec) | stateless |
| Edit | SFTP | stateless |
| MultiEdit | SFTP | stateless |
| MultiRead | exec (one command) | stateless |
| FileStat | SFTP stat | stateless |
| Bash | persistent bash channel | stateful |
| Glob | exec | stateless |
| Grep | exec | stateless |
| Feedback | local file write | local only |

Feedback 是个例外：它写入本地文件，从不触碰 SSH 连接。它捕获 agent 对工具本身的观察，而非对远程系统的观察。请参阅[开发反馈循环](./feedback-loop.md)。
