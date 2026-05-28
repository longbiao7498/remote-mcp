# 可配置 cwd 与路径解析

> English version: [cwd-and-path-resolution.md](./cwd-and-path-resolution.md)

> 另见：[v0.2.0 设计规范 §6](../../superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md)（权威版本）。

在 v0.1.x 中，每个工具都需要绝对路径。`Read("config.yaml")` 会因 `File not found` 而报错。agent 必须了解远程目录结构并手动拼接路径：`Read("/opt/myapp/config.yaml")`。

在 v0.2.0 中，你可以为每台主机配置 `cwd`（`--cwd /opt/myapp`），相对路径以此为锚点解析。`Read("config.yaml")` 现在会读取 `/opt/myapp/config.yaml`。这与 Claude Code 原生在本地项目目录下的工作方式一致。

## 为何是「注册时配置」而非「agent 控制」？

我们考虑过让 agent 通过工具调用来设置或更改 cwd（类似有状态的 `cd`）。被拒绝，原因有二：
1. 非持久 Bash 意味着 agent 的 `cd` 本来就不持续——在此之上再加一个 agent 控制的 cwd，等于又引入了一个并行的状态机，令人困惑。
2. CC 原生 cwd 在会话开始时固定（`claude` 启动时所在的目录）。镜像这一设计可以保持 CC 原生与 remote-mcp 之间 agent 行为的可预期性。

## 为何是后缀 `[host=X cwd=Y]` 而非前缀？

后缀出现在每个工具输出中（成功、错误、重连警告）。这样设计是刻意为之：
- **后缀**，这样 Read 的 `     1\t...` 行号格式就不会被误认为是前缀
- **配置的 cwd，而非运行时 pwd**，这样 agent 始终看到稳定的「我在 X 中」心智模型——即使 agent 的 `command` 执行了 `cd /tmp`，下一次调用仍从配置的 cwd 开始，后缀也反映这一点

这是一种主动提示，而非被动纠错。agent 本来就不应该形成错误的心智模型。

## 为何工具参数中的 `~` 被拒绝

波浪号展开需要知道远端用户的 `$HOME`，而 agent 并不知道（也不应该假设）。MCP 服务器会在建立连接时一次性展开 `cwd` 配置字段中的 `~`，但工具参数保持字面值——请传递绝对路径或相对于 cwd 的路径。如果你真的需要在工具参数中使用 `$HOME`，请使用 RemoteInfo 报告的值。

## `~` 双层策略摘要

- **cwd 配置**（`--cwd ~/projects/myapp` 或 `cwd: ~/projects/myapp`）：在连接时展开
- **工具参数**（`Read("~/foo.txt")`）：报错——请传递绝对路径或相对于 cwd 的路径
