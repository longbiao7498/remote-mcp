# remote-mcp

> English version: [README.md](./README.md)

一个本地 Python MCP 服务器，通过 SSH 把文件和 Shell 工具代理到远程 Linux 主机。Claude Code（以及任何其他 MCP 客户端）会获得 10 个工具——`Read`、`Write`、`Edit`、`MultiEdit`、`MultiRead`、`FileStat`、`Bash`、`Glob`、`Grep`、`Feedback`——所有操作都在远程主机上执行。

## 快速开始

```bash
git clone <repo>
cd remote-mcp
pip install -e .
```

然后 [教程](./docs/tutorial/first-remote-session.zh.md) 会带你从这里走到完整可用的环境，大约 15 分钟。

## 文档

全部文档在 [`docs/`](./docs/) 目录下，按 [Diátaxis](https://diataxis.fr/) 框架组织：

| | 我想... | 读 |
|---|---|---|
| 📘 | **第一次让某个功能跑起来** | [`docs/tutorial/`](./docs/tutorial/) |
| 🛠 | **解决一个我已经遇到的具体问题** | [`docs/how-to/`](./docs/how-to/) |
| 📚 | **查精确的参数 / 错误 / 配置** | [`docs/reference/`](./docs/reference/) |
| 💡 | **理解系统为何这样设计** | [`docs/explanation/`](./docs/explanation/) |

每篇文档都是中英双语——每个 `name.md` 都有对应的 `name.zh.md`。

## 项目状态

v0.1.0——见 [`CHANGELOG.md`](./CHANGELOG.md)。

设计历史（规范文档和执行计划）保留在 [`docs/superpowers/`](./docs/superpowers/) 下，方便审视项目的来龙去脉。

## 许可证

MIT——见 [`LICENSE`](./LICENSE)。

## 参与贡献

见 [`CONTRIBUTING.md`](./CONTRIBUTING.md) 以及面向开发者的操作指南：[添加一个新工具](./docs/how-to/add-a-new-tool.zh.md)。
