# 参与贡献 remote-mcp

> English version: [CONTRIBUTING.md](./CONTRIBUTING.md)

## 优先阅读

在做任何重大改动之前：

1. 完整设计文档——[`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`](./docs/superpowers/specs/2026-05-26-remote-mcp-design.md)。许多决策（sentinel 协议、PTY 分配、后台 bash 用 `setsid`、重连 WARNING 协议）都有明确的理由。先看 spec 再讨论是否要推翻。
2. 架构心智模型——[`docs/explanation/architecture.zh.md`](./docs/explanation/architecture.zh.md)。
3. 设计决策记录——[`docs/explanation/design-decisions.zh.md`](./docs/explanation/design-decisions.zh.md)（每个关键决策记录了：决策、考虑过的备选方案、为何选择 X）。

## 开发环境

```bash
git clone <repo>
cd remote-mcp
pip install -e ".[dev]"
```

需要 Python 3.8+。会装 `paramiko`、`mcp`、`pyyaml`，外加开发依赖（`pytest`、`pytest-asyncio`、`docker`）。

## 跑测试

两层：

```bash
# 单元测试（不依赖 SSH，快）
pytest tests/unit/ -v

# 集成测试（需要可达的 SSH 主机，较慢）
pytest tests/integration/ -v

# 全部
pytest tests/ -v
```

### 集成测试需要 SSH 主机

默认 fixture 指向 `penglin_lb@192.168.10.20`。用环境变量覆盖：

```bash
export RMCP_TEST_HOST=your.host
export RMCP_TEST_USER=youruser
export RMCP_TEST_PORT=22
export RMCP_TEST_KEY=~/.ssh/id_ed25519
pytest tests/integration/ -v
```

主机不可达时集成测试会被 skip——不算失败。

测试隔离：每个 session 在远程主机上创建唯一的 `/tmp/rmcp-test-<uuid>/` 目录，session 结束时清理。后台 bash 测试产生的 `/tmp/rmcp-bg-*.log` 故意不自动清理（保留供事后分析）。

## 添加新工具

这是独立的操作指南：[`docs/how-to/add-a-new-tool.zh.md`](./docs/how-to/add-a-new-tool.zh.md)。它用具体的 `Touch` 工具例子带你走完 5 个改动点（工具函数、schema、dispatch、测试、文档）。

## 提交规范

Conventional commits，英文：

```
feat(tools): Touch — create empty file or update mtime
fix(connection): expand ~ in key_path
docs: clarify Bash run_in_background usage
test(bash_session): cover ANSI escape stripping
build: bump paramiko to 3.4
```

## 设计原则（修改之前先讨论）

1. **所有工具返回字符串**。错误用 `"Error: ..."` 字符串表达；工具永远不抛异常。agent 读字符串并据此调整。完整目录见 [`docs/reference/errors.zh.md`](./docs/reference/errors.zh.md)。
2. **与原生工具保真**。`Read`/`Write`/`Edit`/`MultiEdit`/`Bash`/`Glob`/`Grep` 的 schema 和输出格式逐字对齐 Claude Code 原生工具。没有强理由不要加参数或改输出。
3. **带宽敏感**。任何跨网络的操作都是成本。优先用服务器端过滤（`Grep`）、服务器端切片（`Read`）、批量（`MultiRead`、`MultiEdit`）、SFTP 原生操作。参见 [`docs/explanation/bandwidth-and-latency.zh.md`](./docs/explanation/bandwidth-and-latency.zh.md)。
4. **每进程一个 SSH Transport**。所有 file/exec/bash 操作在同一个 paramiko `Transport` 上多路复用。除非 `ProxyJump` 要求，不要另开 client。参见 [`docs/explanation/architecture.zh.md`](./docs/explanation/architecture.zh.md)。
5. **优雅重连**。SSH 断了 → 自动重连一次 → 下一次工具调用结果前缀加 `[WARNING]`（带主机名），让 agent 知道 shell 状态已重置。**绝不静默恢复**。参见 [`docs/explanation/reconnect-and-warning.zh.md`](./docs/explanation/reconnect-and-warning.zh.md)。

## 提交你自己的反馈

如果你是 agent 在使用这个工具并发现了 bug 或想到了有用的功能，用 `Feedback` 工具。输出写到 `~/.local/share/remote-mcp/feedback.jsonl`。维护者怎么读这些反馈见 [`docs/how-to/inspect-feedback-log.zh.md`](./docs/how-to/inspect-feedback-log.zh.md)。

## 提问渠道

开 GitHub issue。私下开发期间，Feedback log 就是 issue tracker。
