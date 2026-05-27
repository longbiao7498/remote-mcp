# remote-mcp

> English version: [README.md](./README.md)

一个本地 Python MCP 服务器，通过 SSH 把文件和 Shell 工具代理到远程 Linux 主机。Claude Code（以及任何其他 MCP 客户端）会获得 10 个工具——`Read`、`Write`、`Edit`、`MultiEdit`、`MultiRead`、`FileStat`、`Bash`、`Glob`、`Grep`、`Feedback`——所有操作都在远程主机上执行。

当你的代码在一台只开放 SSH 的服务器上、又不想往上面装任何东西时，这个项目就是补这个缝的。

## 环境要求

- Python 3.8+
- 一台 SSH 可达的 Linux 主机（你已经能 `ssh user@host` 免密登录）
- 本地装好 Claude Code（或其他 MCP 客户端）

## 安装

```bash
git clone https://github.com/longbiao7498/remote-mcp.git
cd remote-mcp
pip install -e .
```

这是个纯 Python 项目——没有编译步骤。`pip install` 会拉取 `paramiko`、`mcp`、`pyyaml`。

## 配置

创建 `~/.config/remote-mcp/config.yaml`：

```yaml
hosts:
  myserver:
    hostname: 192.168.1.100
    user: alice
    key_path: ~/.ssh/id_ed25519

default_host: myserver
```

最简配置就这样。完整 schema（多主机、ProxyJump、按主机调参）在 [`docs/reference/config-schema.zh.md`](./docs/reference/config-schema.zh.md)。

## 验证

```bash
python -m remote_mcp --host myserver --test
```

预期输出：

```
Connected to myserver (alice@192.168.1.100). All tools: OK
```

看到这行就说明 SSH 连接没问题，`remote-mcp` 健康。如果报错，参见 [断连恢复指南](./docs/how-to/recover-from-disconnect.zh.md)。

## 在 Claude Code 中注册

每个主机一次 `claude mcp add`：

```bash
claude mcp add --scope user remote-myserver -- python -m remote_mcp --host myserver
```

重启 Claude Code。工具列表里会出现 10 个新工具，命名形如 `mcp__remote-myserver__Read`、`mcp__remote-myserver__Bash` 等。试着对 agent 说：*"用远程工具看看 /etc/hostname"*，就能看到它们工作。

> **哪些是用户自己选的、哪些是固定 CLI 语法** —— 这条命令里有两个**你自己选**的 token，它们在这个例子里恰好长得一样，必须先把"你选"和"CLI 固定写法"分开看。
>
> 命令结构：
>
> ```
> claude mcp add --scope user  <NAMESPACE>  --  python -m remote_mcp --host  <HOST-KEY>
> └── 固定 Claude Code CLI ──┘└你选┘    ↑   └── 固定 remote-mcp CLI ──┘└你选┘
>                                      │
>                                      └ 分隔符: "后面这串是要执行的命令"
> ```
>
> 两个**你选**的 token 互相独立：
>
> - **`<NAMESPACE>`** —— Claude Code 用来标识这个 MCP 服务器的标签。它会成为 agent 看到的**工具前缀**：`mcp__<NAMESPACE>__Read`、`mcp__<NAMESPACE>__Bash` 等。后续 `claude mcp remove <NAMESPACE>`、`claude mcp list` 都用它。字母数字加横线即可。
> - **`<HOST-KEY>`** —— `~/.config/remote-mcp/config.yaml` 里 `hosts:` 块下的 key。告诉 `remote-mcp` 实际要 SSH 到**哪台**远程主机。必须精确匹配。
>
> 命令里其余部分（`claude mcp add`、`--scope user`、`--`、`python -m remote_mcp`、`--host`）都是**固定 CLI 语法**——照抄即可。
>
> **两个具体例子：**
>
> ```bash
> # 推荐写法（两个名字一致，最不混淆）：
> claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
> # agent 看到：mcp__remote-prod__Read, ...，实际操作 'prod' 主机
>
> # 也合法（名字不一致，少见但能用）：
> claude mcp add --scope user box42 -- python -m remote_mcp --host gpu-server-01
> # agent 看到：mcp__box42__Read, ...，实际操作 'gpu-server-01' 主机
> ```
>
> **命名习惯**：`<NAMESPACE>` 加 `remote-` 前缀（与本地 MCP 服务器区分），并设为 `remote-<HOST-KEY>` 形式（命名空间一眼能看出操作哪台远程）。多主机场景见 [配置多台远程主机](./docs/how-to/configure-multi-host.zh.md)。

## 推荐：加上工作流引导文档

agent 知道带宽感知的工作模式后会用得更高效（用 Grep 的 context 行替代 grep 后再 Read、用 MultiRead 替代连续 Read、用后台 Bash 替代长任务阻塞等）。把 [`CLAUDE.md.fragment.zh.md`](./CLAUDE.md.fragment.zh.md) 的内容复制到你远程项目的 `CLAUDE.md` 里，agent 会自动遵守这些规则。

## 接下来读什么

全部文档在 [`docs/`](./docs/) 下，按 [Diátaxis](https://diataxis.fr/) 框架组织——按你的需求挑入口：

| | 我想... | 读 |
|---|---|---|
| 📘 | **从头跟一遍带手把手的完整流程** | [`docs/tutorial/first-remote-session.zh.md`](./docs/tutorial/first-remote-session.zh.md) |
| 🛠 | **解决具体问题**（多主机、慢网络、MCP 不出现等） | [`docs/how-to/`](./docs/how-to/) |
| 📚 | **查精确参数、错误、配置** | [`docs/reference/`](./docs/reference/) |
| 💡 | **理解设计思路**（为何选 paramiko、为何持久 bash、WARNING 文本为何那样写等） | [`docs/explanation/`](./docs/explanation/) |

每页都是中英双语——每个 `name.md` 都对应一个 `name.zh.md`。

## 项目状态

v0.1.0——见 [`CHANGELOG.zh.md`](./CHANGELOG.zh.md) 了解本次发布的内容，[`docs/superpowers/specs/`](./docs/superpowers/specs/) 是原始设计规范。

## 许可证

MIT——见 [`LICENSE`](./LICENSE)。

## 参与贡献

见 [`CONTRIBUTING.zh.md`](./CONTRIBUTING.zh.md) 以及面向开发者的操作指南：[添加一个新工具](./docs/how-to/add-a-new-tool.zh.md)。
