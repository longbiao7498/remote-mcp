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
                    │   Native filesystem (via SFTP)           │
                    │   Per-call exec channels (incl. Bash)    │
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
│  │  ┌─────────────────┐  ┌──────────────────────────────┐  │   │
│  │  │   SFTP client   │  │ exec ×N  (short-lived,        │  │   │
│  │  │  (lazy-init,    │  │ per call — Bash, Glob, Grep,  │  │   │
│  │  │  reused for all │  │ Read, MultiRead, and all       │  │   │
│  │  │  file ops)      │  │ other command-running tools)  │  │   │
│  │  └─────────────────┘  └──────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  disconnect / reconnect → entire Transport subtree is rebuilt   │
└─────────────────────────────────────────────────────────────────┘
```

### Bash 工具的逐调用 exec 通道（v0.2.0+）

自 v0.2.0 起，Bash 工具不再保持一个持久 bash 进程存活。每次 Bash 工具调用都会打开一个新的 exec 通道，运行命令，完成后关闭通道——与 Glob、Grep、Read（sed 路径）和 MultiRead 使用的模型相同。调用之间不存在共享的 shell 状态。

「shell 环境只加载一次」的便利性通过**快照机制**得以保留：在建立连接时，`bash -ic 'declare -p; declare -fp; alias'` 会捕获 bashrc 加载后的环境（PATH、别名、conda init 等），并将其写入远程主机上的一个快照文件。每次 Bash 调用在运行用户命令之前都会 `source` 此快照，使 PATH 和其他启动环境值可用——而无需在每次调用时都支付 bashrc 启动开销。

配置的 `cwd`（在注册时通过 `--cwd` 设置）以 `cd <cwd>` 的形式追加到快照末尾，因此每次 Bash 调用都从正确的工作目录开始。关于这如何融入更广泛的路径处理模型，请参阅[可配置 cwd 与路径解析](./cwd-and-path-resolution.md)。

这一变更的深层原因记录在[为何采用非持久 Bash](./why-non-persistent-bash.md)中。

### SFTP 客户端

SFTP 在第一次文件操作时懒初始化，此后复用。它专门用于文件读、写和编辑操作。选择 SFTP 而非 shell 命令来进行文件 I/O 是经过深思熟虑的：SFTP 是二进制安全的，无需 shell 转义，并且复用了已打开的通道。一个包含单引号、美元符号或换行符的文件，无需任何特殊处理即可正确传输。

Write 工具利用 SFTP 自身的 mkdir 能力来创建父目录，避免了额外的 exec 通道往返。

### 临时 exec 通道

Glob 和 Grep 使用 `SSHConnection.exec()`，它会打开一个新通道、运行命令、读取结果，然后关闭通道。这些工具本质上是无状态的——grep 调用没有「当前目录」的概念。exec 模型正是合适的选择：简单、隔离、无共享状态可能被破坏。

Read 工具的远端 `sed` 切片以及 MultiRead 构造的多文件脚本，也都使用 exec 通道。

## 两条执行路径

每次工具调用最终走向两条路径之一：

**Exec 路径**（Bash、Glob、Grep、Read、MultiRead、Write 的 mkdir）：`SSHConnection.exec(command)` 打开通道、运行命令、返回 stdout + stderr + 退出码，然后关闭通道。无共享状态，无持久性，无顺序约束。自 v0.2.0 起，Bash 也加入了这条路径——它在通过 exec 运行命令之前，先用快照 `source` 对用户命令进行包装，而不再使用持久 bash 通道。

**SFTP 路径**（Read 完整文件、Write、Edit、MultiEdit、MultiRead 数据、FileStat）：操作通过持久 SFTP 通道进行，无需打开新的 exec 通道。二进制安全，无需 shell 转义。

这种分离是举足轻重的。SFTP 能可靠地处理文件内容，无论文件中包含什么字符。Exec 能干净地处理命令执行，无需持久 bash 会话的复杂性。

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

| 工具 | 通道类型 | 说明 |
|------|-------------|------|
| Read (sed path) | exec | 无状态 |
| Write | SFTP (mkdir via exec) | 无状态 |
| Edit | SFTP | 无状态 |
| MultiEdit | SFTP | 无状态 |
| MultiRead | exec (one command) | 无状态 |
| FileStat | SFTP stat | 无状态 |
| Bash | exec（快照包装） | 逐调用无状态；快照提供环境 |
| Glob | exec | 无状态 |
| Grep | exec | 无状态 |
| Feedback | local file write | 仅本地 |

Feedback 是个例外：它写入本地文件，从不触碰 SSH 连接。它捕获 agent 对工具本身的观察，而非对远程系统的观察。请参阅[开发反馈循环](./feedback-loop.md)。
