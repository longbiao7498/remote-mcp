# 操作指南

> English version: [`README.md`](./README.md)

操作指南是解决具体问题的**操作手册**。你已经知道想要完成什么——这里告诉你具体步骤。指南假设你已基本熟悉 remote-mcp（如果还不熟悉，请先阅读[教程](../tutorial/first-remote-session.md)）。

操作指南既不是教程（不讲解概念，没有引导式学习），也不是参考文档（不穷举所有选项——只列出解决特定问题所需的步骤）。

## 操作 remote-mcp

| 指南 | 适用场景 |
|-------|-------------|
| [配置多个远程主机](./configure-multi-host.md) | 在同一个 Claude Code 会话中操作 2–3 台服务器 |
| [设置 ProxyJump（堡垒机）](./set-up-proxyjump.md) | 目标主机只能通过跳板机访问 |
| [针对慢速/不稳定网络调优](./tune-for-slow-networks.md) | 处于高延迟或带宽受限的网络环境 |
| [运行长时间后台任务](./run-long-background-jobs.md) | 需要启动耗时数分钟的构建/测试/安装任务，且不希望阻塞 agent |
| [连接断开后恢复](./recover-from-disconnect.md) | 看到 `[WARNING] SSH connection to <host> was lost` 消息时 |
| [调试：MCP 工具未出现在 Claude Code 中](./debug-mcp-not-appearing.md) | 执行 `claude mcp add` 并重启后，工具没有显示 |
| [查看反馈日志](./inspect-feedback-log.md) | 读取 agent 记录的 remote-mcp 相关反馈 |
| [使用 CLAUDE.md 工作流片段](./use-the-workflow-fragment.zh.md) | 把工作流规则复制到你**本地**的 CLAUDE.md，让 agent 自动使用带宽感知模式 |

## 扩展 remote-mcp

| 指南 | 适用场景 |
|-------|-------------|
| [添加新工具](./add-a-new-tool.md) | 想向 agent 暴露新能力时 |

## 操作指南的写作规范（供贡献者参考）

- 陈述问题 → 编号步骤 → 完成。不需要解释问题为何存在的前言。
- 不讲解概念——如有必要，链接到 `explanation/` 目录。
- 不罗列所有选项——只选择解决特定问题的那条路径；其他选项交叉链接到参考文档。
- 一篇指南对应一个具体结果。如需涵盖不同情形，拆分为多篇指南。
