# 网络故障契约

> English version: [network-failure-contract.md](./network-failure-contract.md)

> See also: [the v0.2.2 spec](../superpowers/specs/2026-05-28-network-robustness-design.md), authoritative.

remote-mcp 的职责是通过 SSH 代理文件和 shell 操作。SSH 连接可能以多种方式失败——正常断开、笔记本休眠期间静默丢包、完全网络中断。早期版本对某些情况处理得当，对另一些则完全未作处理。v0.2.2 针对网络故障下的工具行为建立了统一的行为契约。

## 三条规则

1. **有界时间返回。** 每次工具调用都必须在有限时间内返回，即使网络出现异常。任何调用都不得无限期地等待远端响应而挂起。

2. **成功与失败可区分。** 现有的 `Error: ...` 约定已经足够——agent 已经可以通过 `Error:` 前缀进行模式匹配。我们不引入结构化的错误码；重要的是错误响应不能被误认为成功响应，反之亦然。

3. **不撒谎。** 当工具返回 `Error: ...` 时，不得声明与远端实际状态相反的结果。如果远端任务已成功执行但响应在传输中丢失，我们不会返回 `Error: ... failed`。如果远端状态未知，我们明确说明，而不是猜测。

这些契约在框架层（`connection.py`、`server.py`）强制执行，因此各工具的代码保持简洁。新工具无需实现错误分析逻辑——它们只需返回输出或 `Error:` 字符串即可。

## 为什么需要这些规则——四个具体故障

**Edit / MultiEdit 自动重试假阴性。** SFTP 在远端完成了写入，但响应在传输中丢失。v0.2.1 的自动重试会重新执行 Edit，此时文件已被修改，结果返回 `Error: old_string not found`。agent 以为 Edit 失败，可能再试一次，从而破坏已正确修改的文件。v0.2.2：Edit / MultiEdit / Bash 不再自动重试，由 agent 决定。

**SFTP 静默挂起。** SFTP 通道没有 I/O 超时。笔记本休眠 → SFTP 等待数分钟却等不到响应。v0.2.2：`op_timeout_default`（默认 60s）使 paramiko 在空闲窗口后抛出 `socket.timeout`。

**后台 bash 孤儿进程。** `setsid nohup bash -c "..." &; echo $!` — bash 进程实际上已启动，但 `echo $!` 的响应丢失了。agent 以为启动失败，却不知道存在一个孤儿进程。v0.2.2：PID 在 echo 之前写入 `/tmp/rmcp-bg-<uuid>.pid`。即使 echo 响应丢失，agent 也可以 `cat /tmp/rmcp-bg-*.pid` 来恢复。

**快照重建谎报 WARNING。** `_create_snapshot` 静默失败（仅有 stderr），但 WARNING 文本声称 `Snapshot was rebuilt`。agent 以为环境完好，后续 Bash 调用却神秘失败。v0.2.2：快照在 MCP 启动时捕获一次，存储在本地内存中，并持久化到 `~/.cache/remote-mcp/`。重连不会重新运行 `bash -ic`；而是对远端文件进行 stat 检查，若缺失则从本地缓存重新上传。WARNING 文本有三种变体，反映实际状态。

## 对 agent 的影响

大多数故障仍会自愈：幂等读操作（Read、Glob、Grep、FileStat、MultiRead、Write、Upload、Download）在 SSH 故障时完全按之前的方式自动重试，透明地完成重连。唯一对 agent 可见的行为变化是 Edit / MultiEdit / Bash：对于之前会被透明重试的网络抖动，它们现在可能返回 `Error: <SSHException>: ...`。这是正确性上的权衡——静默重试读-改-写或有状态命令带来的问题，比显式报错更严重。

关于如何应对新的 `Error:` / WARNING 字符串的 agent 级别指导，请参阅 `CLAUDE.md.fragment.md`。
