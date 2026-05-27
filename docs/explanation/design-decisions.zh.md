# 设计决策

> English version: [design-decisions.md](./design-decisions.md)

本文档解释 remote-mcp 中的关键选择、我们考虑过哪些备选方案，以及为何做出这些选择。这里的推理过程与决策本身同等重要——如果你正在考虑修改某个地方，理解「为什么」会告诉你是否正在打破某个举足轻重的设计。

## SSH 库：paramiko 与备选方案

**决策：** 使用 paramiko。

**考虑过的备选方案：**
- `asyncssh`：完全异步，API 更现代，但增加了一个非平凡的依赖，并要求整个代码库严格遵守「从头到尾全部异步」的纪律。
- `subprocess` + 系统 `ssh` 二进制：零额外依赖，但几乎不提供任何控制——没有编程式 keepalive、没有 ProxyJump 通道 API、没有 SFTP 客户端，而且系统 `ssh` 必须以难以从 Python 验证的方式正确配置。
- Fabric / Invoke：paramiko 或 subprocess 的便利性封装，不适合需要精细通道控制的库。

**为何选择 paramiko：** 硬性约束决定了这个选择。我们需要 SFTP（二进制安全的文件传输）、SSH 协议层的 keepalive 控制，以及以 `direct-tcpip` 通道而非 shell 管道实现的 ProxyJump。paramiko 通过稳定的 API 提供了全部三者，无需其他依赖。asyncssh 的异步模型被拒绝，是因为 MCP 服务器的异步层（`mcp` SDK）和 SSH 层仅在单一的 `call_tool` 边界处交互；在异步上下文中以 `asyncio.to_thread` 运行同步 paramiko 调用是直接可行的，而将所有内容重构为 asyncssh 则会增加复杂度而无实质收益。

## 传输方式：stdio MCP 与 HTTP MCP

**决策：** stdio MCP。

**考虑过的备选方案：**
- HTTP MCP（SSE Transport）：允许 MCP 服务器作为持久守护进程运行，可同时被多个 Claude Code 会话访问。

**为何选择 stdio：** 目标配置是每个用户会话对应一台远程主机。stdio MCP 由 Claude Code 直接派生和管理——不需要开放端口，不需要守护进程保活，客户端与服务器之间不需要认证。进程生命周期很简单：「Claude Code 正在运行」等于「进程正在运行」。HTTP MCP 会为一个明确超出范围的多会话用例增加运维复杂度（端口冲突、守护进程生命周期、安全性）。「2-3 台主机，而非一个机群」的设计约束使 stdio 成为明显正确的答案。

## 每主机一个进程 vs. 联邦服务器

**决策：** 每台远程主机一个操作系统进程，通过 `claude mcp add` 分别注册。

**考虑过的备选方案：**
- 一个进程管理所有远程主机，工具名称类似 `Read(host="prod", path="...")`。

**为何选择每主机一进程：** 三个原因。第一，隔离性：如果到某台主机的 SSH 连接出现异常或崩溃，它不会影响其他主机上的操作。进程边界提供了免费的崩溃隔离。第二，简单性：代码库中没有主机路由逻辑，没有单进程内的每主机状态多路复用，没有需要推理的共享连接池。第三，命名：Claude Code 的 MCP 命名空间（`mcp__remote-prod__Read`）已经将主机标识编码在工具名称中，使 agent 行为更加清晰——agent 在工具调用层面就能知道自己在操作哪台主机。联邦设计会要求 agent 在每次调用时都传递 `host=` 参数，产生一个新的错误来源和更复杂的 schema。

代价是线性的资源增长：N 台主机意味着 N 个进程、N 条 SSH 连接、N 个 bash 会话。对于 2-3 台主机，这可以忽略不计。关于规模更大时会发生什么，请参阅[多主机模型](./multi-host-model.md)。

## 持久 bash 会话 vs. 全部用 exec

**决策：** 在 Transport 的生命周期内保持一个 bash 进程存活；将它用于所有 Bash 工具调用。

**考虑过的备选方案：**
- 为每次 Bash 工具调用打开一个新的 exec 通道。简单、无状态、无死锁风险。

**为何选择持久化：** shell 状态持久性不是一个可有可无的功能，它是 Bash 工具的核心价值主张。当 agent `cd` 进入一个项目目录时，它期望后续命令在那里运行。当它 `export` 一个环境变量（激活 Python 虚拟环境、设置 `CARGO_HOME`、设置数据库 URL）时，它期望该变量在后续命令中可见。无状态的 exec 模型会要求 agent 在每次调用时重建工作上下文——这既脆弱又浪费带宽。

持久化的代价是显著的：我们需要 sentinel 协议、后台 reader 线程以及仔细的初始化。这些是真实的复杂性，但它们是必要的复杂性，而非偶然产生的。

## Sentinel 协议 vs. 其他命令边界检测方案

**决策：** 在每条命令后追加 `echo "RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)"`；逐行读取 stdout，直到 sentinel 出现。

**考虑过的备选方案：**
- **带提示词检测的伪终端（PTY）：** 分配一个 PTY，设置已知的提示字符串如 `PS1=RMCP_DONE> `，将提示词检测为命令边界。这是 Fabric 交互模式等交互式 SSH 工具的工作方式。
- **独立的状态通道：** 在一个 exec 通道中运行命令，在延迟后在第二个通道中运行状态检查。
- **固定分隔符注入：** 始终向独立的文件描述符写入已知字符串，在该 fd 上检测。

**为何选择 sentinel：** PTY 分配因一个具体而重要的原因被拒绝：PTY 引入了会破坏输出的终端仿真语义。控制序列、换行处理以及本意发给终端仿真器的 ANSI 转义码会出现在原始输出流中。更关键的是，PTY 以交互模式运行 shell，这会重新引入作业控制通知和其他我们明确用 `set +m` 抑制的交互行为。sentinel 方案以非交互模式运行 bash，输出干净且可预测。

sentinel 本身对意外碰撞具有鲁棒性：每次调用都生成一个新的 UUID，因此用户命令的输出不可能包含当前调用的 sentinel（那需要预测 UUID）。sentinel 还在同一行中携带退出码和当前工作目录，省去了对这两个信息的后续查询。

后台 reader 线程是 sentinel 方案的必要伴侣。如果本地端停止从通道消费字节，paramiko 的接收缓冲区会填满，远端 bash 在写入时阻塞，sentinel 永远不会到来——死锁。reader 线程将缓冲区持续排空到行队列中，`execute()` 从队列读取。这不是一个优化，而是正确性的要求。

## PTY 分配：为何我们不请求 PTY

**决策：** 不使用 PTY，bash 以非交互模式运行。

这与上面的 sentinel 讨论密切相关，但值得单独说清楚。PTY 分配是使 Ctrl-C（`\x03`）在 SSH 会话中作为中断信号工作的原因。没有 PTY，向非交互 bash 的 stdin 发送 `\x03` 不会有特殊效果。

然而，在超时路径上，我们确实会发送 `\x03`——而且有效，因为 `exec 2>&1` 将 stderr 合并进 stdout（使通道成为单一流），并且 bash 在非交互模式下从管道读取时确实会在某些条件下响应 `\x03` 的 SIGINT 行为。关键见解在于：我们不需要完整的 PTY 语义——我们只需要中断字符能够到达正在运行的子进程。这无需 PTY 即可工作，且没有 PTY 带来的终端仿真污染。

## 后台进程的 setsid

**决策：** 用 `setsid nohup bash -c <cmd>` 包装后台命令。

**考虑过的备选方案：**
- 普通的 `cmd &`（& 号后台化）
- 不带 `setsid` 的 `nohup cmd &`

**为何选择 setsid：** Bash 工具以 `set +m` 初始化，禁用了作业控制。在没有作业控制的 bash 中，`cmd &` 仍然会创建一个子进程，但它保留在 BashSession 的进程组中。如果 agent 使用 `kill -- -<pid>` 来终止进程树（终止所有子进程的正确方式），负数 PID 意味着「终止整个进程组」——这会包括持久 bash 会话本身，那将是灾难性的。

`setsid` 创建一个新会话，使后台进程成为新进程组的组长，PID = PGID。`kill -- -<pid>` 则精确地终止后台进程及其后代，保持 BashSession 完整。`nohup` 提供了额外的 SIGHUP 信号保护，尽管 `setsid` 已经从控制终端分离了。

不带 `setsid` 的普通 `nohup cmd &` 被拒绝，是因为它没有解决进程组问题——进程仍然与父进程共享进程组。

## 文件操作：SFTP vs. shell 命令

**决策：** 对所有文件读、写和编辑操作使用 SFTP。

**考虑过的备选方案：**
- 通过 exec 用 `cat file` 读取，用 `echo content > file` 或 heredoc 通过 exec 写入。

**为何选择 SFTP：** 基于 shell 的文件 I/O 需要转义。包含单引号、美元符号、反斜杠或空字节的文件，无法通过 `echo` 写入而不进行仔细的引号处理——而在 shell 命令中对任意用户提供的内容正确引号处理是经典的 bug 来源。SFTP 在字节层面操作，不涉及 shell。Write 调用的内容以原始字节传输，并按原样存储。

此外，SFTP 复用了已打开的通道。`exec("cat file")` 调用会打开一个新通道、发送命令、等待结果并关闭通道。SFTP 客户端通过持久 SFTP 通道发送结构化的 `open` + `read` + `close`，每次操作的开销更低。

SFTP 无法帮助的唯一情况是 Read 和 MultiRead 中的 `sed` 切片——SFTP 的读取操作不支持行范围查询，只支持字节范围查询。从字节偏移量重建行边界需要完整的文件传输或两遍处理。使用 exec 加 `sed -n` 更简洁，并避免传输我们不需要的数据。

## Read：远端 sed 切片 vs. SFTP 完整传输

**决策：** Read 通过 exec 使用 `sed -n '{offset},{end}p; {end+1}q'`，而非 SFTP 完整文件传输。

这是 v2 相对于 v1 的变化。v1 通过 SFTP 传输整个文件，然后在 Python 中切片。对于小文件这没问题。但对于 100 MB 的日志文件，而 agent 只想要第 5000–5020 行，v1 传输 100 MB；v2 只传输几 KB。`sed -n` 方案对所有文件大小都严格更优，且对服务端 CPU 的额外负担可以忽略不计。

量化比较请参阅[带宽与延迟](./bandwidth-and-latency.md)。

## 工具保真度策略：匹配 Claude Code 的原生 schema

**决策：** 对于对应 Claude Code 原生工具的六个工具（Read、Write、Edit、Bash、Glob、Grep），工具名称、参数名称和输出格式必须与原生 schema 完全匹配。

**为何：** Claude Code 的 agent 是在原生工具 schema 上训练的。它知道 Read 返回 `"     5\tsome line"`，知道 Edit 失败时说 `"Error: old_string not found in <path>"`。如果 remote-mcp 返回不同的格式——即使看起来很合理——agent 可能会误解结果、错误路由恢复逻辑，或者使用错误的工具。这不是理论上的担忧：设计文档明确指出错误消息的措辞必须完全正确，agent 的恢复策略才能正常工作。

三个新工具（MultiRead、FileStat、Feedback）没有原生对应，因此它们的 schema 设计注重自洽性和抗误用性，而非原生兼容性。

## Write 父目录：SFTP mkdir vs. exec

**决策：** 递归使用 SFTP 自身的 `mkdir`，而非 `conn.exec("mkdir -p ...")`。

v1 在写入前通过 exec 运行 `mkdir -p`，这会打开新的 exec 通道、支付通道建立开销，然后再为写入本身打开 SFTP 通道。v2 使用 SFTP 的 `mkdir` 操作在已打开的 SFTP 通道上实现 `_sftp_mkdirs()`——不需要 exec 通道，少一次往返。

## Glob：带模式转换的 find vs. 远端 glob

**决策：** 使用 `find ... -name` 或 `find ... -wholename`，并配合将 glob 模式转换为 find 表达式的转换层。

**考虑过的备选方案：**
- 启用 globstar 的 `bash -c 'ls **/*.py'`
- `find ... -name '*' | grep -E <pattern>`

**为何选择带转换的 find：** `find` 在 Linux 上普遍可用，产生有序的、可控的输出，并支持 `-name`（仅文件名匹配）和 `-wholename`（完整路径匹配）两者。`**` glob 语法可以干净地转换为递归的 `-name` 匹配。转换层（`_glob_to_find`）对其支持的内容和不足之处是明确的——这种透明度比 shell glob 的隐含行为不匹配要好得多。

已知的局限性是对复杂模式的转换是近似的。这已被明确文档化，对于该工具的既定用途来说是可接受的。

## 所有地方都设置输出上限

**决策：** Read 结果上限 256 KB，Bash 输出上限 100 KB，Glob 结果上限 1000 条。触发上限时追加截断提示。

**为何：** 一个没有上限就运行 `find /` 或 `grep "e" /var/log` 的 agent 可能用数 MB 的数据淹没 MCP 传输，使 Claude Code 会话实际上无法使用。上限不是为了节省带宽——它们是为了防止意外地对对话上下文造成拒绝服务攻击。截断提示告知 agent 结果被截断了，以便它可以缩小查询范围，而不是悄悄地基于不完整的数据行动。

## 重连：自动重试一次，然后警告

**决策：** SSH 断开时，自动尝试一次重连。如果成功，设置标志，使下一次工具调用前置一个 WARNING。如果失败，返回 Error。

**为何只重试一次：** 无限重试意味着工具调用可能会静默地挂起数分钟，而进程在挣扎着重连。一次重试足以处理短暂的网络中断（VPN 重连、短暂的防火墙超时），而不会掩盖真正的中断。关于完整讨论，请参阅[重连与 WARNING 协议](./reconnect-and-warning.md)。

## Feedback：本地文件 vs. 网络遥测

**决策：** Feedback 写入本地 JSONL 文件，从不向任何地方发送数据。

这是一个根本性的隐私立场。agent 可能在 `details` 字段中包含代码片段。那些片段属于用户的项目。遥测端点意味着用户的专有代码在未经明确同意的情况下离开其机器。本地文件模型意味着用户完全拥有数据，可以自行决定是否以及如何与维护者分享。关于更完整的理由，请参阅[开发反馈循环](./feedback-loop.md)。
