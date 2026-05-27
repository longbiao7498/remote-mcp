# 重连与 WARNING 协议

> English version: [reconnect-and-warning.md](./reconnect-and-warning.md)

到远端主机的 SSH 连接可能因多种原因断开：VPN 重连、防火墙空闲超时、网络抖动、服务器重启。remote-mcp 会自动处理这种情况——但恢复不是静默的。本文解释为何自动恢复需要明确的警告、WARNING 说了什么以及每个部分为何重要，以及重连后 agent 可以和不可以依赖哪些状态。

## 为何静默恢复是被禁止的

诱人的做法是静默地重连，让 agent 继续工作，仿佛什么都没发生。这是错误的，而且重要的是，这种错误在某些事情严重出错之前是不可见的。

当 SSH 连接断开时，远端 bash 会话的整个状态都丢失了。远端主机上的 bash 进程已经死亡。重连后启动一个新的，它从头开始：工作目录是 `$HOME`，没有之前命令设置的环境变量，没有 source 过的文件，没有别名。如果 agent 在工作流的第三步——设置 Python 虚拟环境、export 了 `DATABASE_URL`、`cd` 进了 `/opt/myapp`——所有这些都消失了。

一个不知道重连发生的 agent 会继续发出命令，假设之前的上下文完整。它可能运行 `python -m pytest`，期望自己在正确的目录里，却得到一个关于缺少文件的令人困惑的错误，然后试图调试一个看似测试失败的问题，而实际上是上下文崩溃了。这种失败模式是隐蔽的，难以诊断。

静默恢复用一个小的即时困惑（WARNING）换取一个大的潜在困惑（神秘的命令失败）。这不是值得做的权衡。

## 三部分 WARNING 结构

WARNING 文本是一份契约。当 `SSHConnection._reconnected` 在成功重连后被设置时，下一次 `call_tool()` 调用会检查该标志、清除它，并在工具结果前追加这条 WARNING：

```
[WARNING] SSH connection to <host_name> was lost and has been re-established.
The remote bash session has been reset: working directory is now $HOME,
all environment variables set in previous commands are lost.
Use absolute paths and re-run any necessary setup commands.
```

三个部分各有其具体用途：

**「SSH connection to \<host_name\> was lost and has been re-established.」** ——这告诉 agent 发生了什么。在多主机会话中，agent 需要知道哪台主机受到影响。一个模糊的「连接已恢复」消息会让它不确定 `prod` 还是 `gpu` 丢失了状态、哪个 bash 会话需要重新初始化、哪些之前的命令可能已经失败。主机名使中断的范围毫不含糊。

**「working directory is now $HOME, all environment variables set in previous commands are lost.」** ——这告诉 agent 哪些状态丢失了。agent 不能假设重连前的任何内容还存在。具体来说：`cd` 命令在重连后不生效，`export FOO=bar` 在重连后不生效，`source .env` 在重连后不生效。这是 agent 在一个会话中积累的三种最常见的 shell 上下文来源。WARNING 明确地列出它们，以便 agent 可以重建正确的内容。

**「Use absolute paths and re-run any necessary setup commands.」** ——这告诉 agent 该做什么。「绝对路径」是针对 cwd 问题的具体、可操作的指令：如果 agent 在 `/opt/myapp` 中工作，它应该开始明确使用该路径，而不是假设 bash 会话仍在那里。「重新运行设置命令」涵盖了环境变量问题。

这三个部分都是必须的。一个只说「连接已重建」的 WARNING 在第二和第三部分上失败了。一个解释了丢失了什么但没有说下一步该做什么的 WARNING 是不完整的。

## 重连后哪些内容存活，哪些不会

**存活的内容：**
- `SSHConnection` 对象及其配置（主机名、用户、密钥路径、keepalive 设置）
- Claude Code 工具命名空间中的主机注册
- `config.yaml` 中的配置
- 写入远端文件系统的任何文件（写操作通过 SFTP 写到磁盘）

**不存活的内容：**
- bash 会话：cwd、所有 export 的环境变量、source 的文件、shell 函数、别名
- SFTP 客户端：在重连后懒初始化，对调用方透明
- 断开时正在进行的任何工具调用：这些返回错误（连接在操作进行时丢失了）
- 用 `run_in_background=true` 启动的后台进程：这些是旧 bash 会话的子进程或 `setsid` 的后代——如果主机本身仍在运行，`setsid` 过的进程可以存活（它们在自己的会话中），但 agent 在上下文中不再有它们的 PID，在假设它们仍在运行之前应该仔细检查

## 如果重连失败

如果自动重连尝试失败，工具结果是：

```
Error: SSH connection to <host> lost and reconnect failed: <reason>
```

这种情况下没有 WARNING——WARNING 是针对恢复成功但 agent 需要知道状态丢失的情况。重连失败意味着工具调用本身失败了；agent 应该将此告知用户，而不是试图继续。remote-mcp 进程在重连失败后不会退出——它保持存活，以便用户可以调查网络问题并重试。

## 为何只重试一次

一次重试能捕获常见情况（短暂的 VPN 故障、短暂的网络中断），而不会为真正的中断无限期地挂起工具调用。两次重试会将最坏情况的等待时间加倍。指数退避会使首次失败的检测极其缓慢。一次立即重试，如果失败则报错，是弹性与响应性之间正确的平衡。

## 重连标志的生命周期

`_reconnected` 在成功重连后由 `_do_reconnect()` 设置为 `True`。`call_tool()` 中的 `check_and_clear_reconnect_flag()` 读取该标志、清除它，并返回它是否被设置——在一次原子操作中完成。这确保 WARNING 恰好出现一次：在重连后的第一次工具调用上，而不是每次后续调用。「检查并清除」的原子性很重要；如果标志被分开检查和清除，一次并发的工具调用可能会看到该标志两次，或者根本看不到。
