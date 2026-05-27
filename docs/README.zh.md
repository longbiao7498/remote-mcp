# remote-mcp 文档

> English version: [`README.md`](./README.md)

本文档按照 [Diátaxis](https://diataxis.fr/) 框架组织，将文档分为四种类型，分别服务于四种不同的读者需求。

根据你**当前的目标**选择对应的入口：

| 如果你想… | 阅读 | 类型 |
|-----------|------|------|
| **第一次让系统跑起来** | [`tutorial/`](./tutorial/) | 📘 教程 — 引导式课程 |
| **解决一个已知的具体问题** | [`how-to/`](./how-to/) | 🛠 操作指南 — 实用配方 |
| **查询精确的行为、参数、错误** | [`reference/`](./reference/) | 📚 参考手册 — 技术规格 |
| **理解系统为何如此设计** | [`explanation/`](./explanation/) | 💡 概念说明 — 设计理念与原理 |

这四种类型互不混用。教程不会解释为什么选择 paramiko；概念说明不会手把手带你完成配置。如果某个页面承担了太多职责，欢迎提交[反馈](./how-to/inspect-feedback-log.md)。

## 推荐阅读路径

**完全没用过 remote-mcp：**
1. [教程 — 第一次远程会话](./tutorial/first-remote-session.md)（15 分钟）
2. [概念说明 — 架构概览](./explanation/architecture.md)（背景知识）
3. 浏览 [参考手册 — 工具索引](./reference/)（了解有哪些工具可用）

**已经熟悉 remote-mcp，遇到具体问题：**
1. 查阅 [`how-to/`](./how-to/) — 找到最接近的条目
2. 在 [`reference/tools/`](./reference/tools/) 中打开对应工具，查看精确行为
3. 如仍未解决，[检查反馈日志](./how-to/inspect-feedback-log.md)或提交新条目

**参与贡献或修改 remote-mcp：**
1. [概念说明 — 设计决策](./explanation/design-decisions.md)（请先阅读这篇）
2. [操作指南 — 添加新工具](./how-to/add-a-new-tool.md)
3. [参考手册 — 配置结构](./reference/config-schema.md) 和 [错误参考](./reference/errors.md)

## 权威设计记录

`docs/superpowers/` 存放项目的设计历史，与面向用户的文档分开保存：

- [`superpowers/specs/2026-05-26-remote-mcp-design.md`](./superpowers/specs/2026-05-26-remote-mcp-design.md) — v2 设计规格（已实现为 v0.1.0）
- [`superpowers/plans/2026-05-26-remote-mcp-implementation.md`](./superpowers/plans/2026-05-26-remote-mcp-implementation.md) — 已执行的 31 项实现计划

这些文档用于*理解系统的演进过程*，而非日常使用。大多数读者无需阅读。

## 双语支持

`docs/` 下的每篇英文文档都有一个以 `.zh.md` 为后缀的中文对应版本（例如 `tutorial/first-remote-session.md` 和 `tutorial/first-remote-session.zh.md`）。英文版本为权威来源；中文翻译保持同步，但可能落后一个版本。
