# 重连与 WARNING 协议

> English version: [reconnect-and-warning.md](./reconnect-and-warning.md)

到远端主机的 SSH 连接可能因多种原因断开：VPN 重连、防火墙空闲超时、网络抖动、服务器重启。remote-mcp 会自动处理这种情况——但恢复不是静默的。本文解释为何自动恢复需要明确的警告、WARNING 说了什么以及每个部分为何重要，以及重连后 agent 可以和不可以依赖哪些状态。

## 为何静默恢复是被禁止的

诱人的做法是静默地重连，让 agent 继续工作，仿佛什么都没发生。即使在 v0.2.0 非持久 Bash 模型下——没有累积的 shell 状态可以丢失——静默恢复仍然是错误的，原因很重要：agent 理应知道底层传输发生了中断。

在 v0.1.x 持久 bash 模型下，静默重连的后果是严重的：cwd 和所有环境变量都消失了，agent 会在错误的假设下悄悄运行。在 v0.2.0 中，后果较为轻微（快照被重建，配置的 cwd 始终是起点），但静默恢复仍然违反了一个原则：agent 应该对发生的事情有准确的认知。如果重连花了几秒钟，在这段时间内发出的工具调用可能已经失败。agent 应该知道这一点。

静默恢复用一点即时的清晰（WARNING）换取对哪些工具调用成功、哪台主机出了问题，以及当前快照是否反映了最新环境的潜在困惑。这不是值得做的权衡。

## WARNING 结构

WARNING 文本是一份契约。当 `SSHConnection._reconnected` 在成功重连后被设置时，下一次 `call_tool()` 调用会检查该标志、清除它，并在工具结果前追加这条 WARNING：

```
[WARNING] SSH connection to <host_name> was lost and has been re-established.
Snapshot was rebuilt; if your bashrc has changed since the connection started,
the new state takes effect from this point.
```

每个部分各有其具体用途：

**「SSH connection to \<host_name\> was lost and has been re-established.」** ——这告诉 agent 发生了什么。在多主机会话中，agent 需要知道哪台主机受到影响。一个模糊的「连接已恢复」消息会让它不确定是 `prod` 还是 `gpu` 受到了影响。主机名使中断的范围毫不含糊。

**「Snapshot was rebuilt; if your bashrc has changed since the connection started, the new state takes effect from this point.」** ——这告诉 agent 在 v0.2.0 非持久模型下重连的唯一有意义的后果。由于每次 Bash 调用本来就从 source 快照的全新 shell 开始，没有什么累积的 shell 状态会丢失。agent 唯一需要知道的是：快照已从当前 bashrc 重建——如果 bashrc 在中断期间发生了变化，新的 Bash 调用将反映这些变化。agent 可以完全照常继续发出命令，无需任何恢复操作。

这是相对于 v0.1.x WARNING 的刻意简化，v0.1.x 要求 agent「使用绝对路径并重新运行设置命令」。那条建议在持久 bash 下是正确的（cwd 和环境变量会丢失），但在 v0.2.0 中不再必要：配置的 cwd 固定在 `config.yaml` 中，快照机制确保每次调用都能自动获得环境设置。

## 重连后哪些内容存活，哪些不会

**存活的内容：**
- `SSHConnection` 对象及其配置（主机名、用户、密钥路径、keepalive 设置、配置的 cwd）
- Claude Code 工具命名空间中的主机注册
- `config.yaml` 中的配置
- 写入远端文件系统的任何文件（写操作通过 SFTP 写到磁盘）
- 生效的 cwd：由于 cwd 在注册时配置（而非作为 bash 会话状态追踪），重连后每次 Bash 调用仍从配置的 cwd 开始

**不存活的内容：**
- 远端 `/tmp` 上的 bash 快照文件：在重连后重建。中断期间对 bashrc 的任何更改都会反映在新快照中。
- SFTP 客户端：在重连后懒初始化，对调用方透明
- 断开时正在进行的任何工具调用：这些返回错误（连接在操作进行时丢失了）
- 用 `run_in_background=true` 启动的后台进程：这些是 `setsid` 的后代，生活在自己的会话中——如果主机本身仍在运行，`setsid` 过的进程可以存活，但 agent 在假设它们仍在运行之前应该仔细检查（用 `kill -0 <pid>`）

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
