# 第一次远程会话

> English version: [first-remote-session.md](./first-remote-session.md)

本教程将带你从一次全新的 `git clone` 开始，直到 Claude Code 成功通过 remote-mcp 工具读取你远程服务器上的文件。整个过程大约需要 15 分钟。

你将在本地安装 remote-mcp、编写一个配置文件、验证 SSH 连接、将服务器注册到 Claude Code，并亲眼看到代理第一次调用 `mcp__remote-myserver__Read`。

---

## 开始之前

在开始前，请确保以下四项全部就绪。任何一项缺失，本教程都将无法正常进行。

- **本地机器上安装了 Python 3.8 或更高版本。**
  ```bash
  python --version
  ```
  你应该看到类似 `Python 3.11.4` 的输出。如果提示 `command not found`，请先安装 Python。

- **一台你可以通过 SSH 登录的远程 Linux 主机。** 你必须能够运行以下命令并进入 shell：
  ```bash
  ssh user@your-host.example.com
  ```
  如果还不行，请先修复你的 SSH 配置再继续。remote-mcp 无法替你完成这一步。

- **已安装并可正常使用的 Claude Code。** 运行 `claude --version` 应能打印出版本号。

- **SSH 密钥（而非密码）。** 本教程使用基于密钥的认证方式。如果你当前的 `ssh user@host` 使用密码登录，请先将你的公钥添加到远程主机的 `~/.ssh/authorized_keys` 文件中。

---

## 第一步 — 克隆并安装

在你的**本地**机器上克隆仓库，并以可编辑模式安装。

```bash
git clone https://github.com/your-org/remote-mcp.git
cd remote-mcp
pip install -e .
```

你应该看到 pip 解析并安装三个依赖项——`paramiko`、`mcp` 和 `pyyaml`——最后以类似以下内容结束：

```
Successfully installed mcp-... paramiko-... pyyaml-... remote-mcp-0.1.0
```

确认包可以正常导入：

```bash
python -m remote_mcp --help
```

你应该看到：

```
usage: remote_mcp [-h] --host HOST [--config CONFIG] [--test]
...
```

看到这个输出，说明安装成功。

---

## 第二步 — 编写最简配置文件

创建配置目录并新建一个文件：

```bash
mkdir -p ~/.config/remote-mcp
```

接着创建 `~/.config/remote-mcp/config.yaml`，内容如下。将其中三个占位值（`myserver`、`your-host.example.com`、`alice`、`~/.ssh/id_ed25519`）替换为你实际的主机信息。

```yaml
hosts:
  myserver:
    hostname: your-host.example.com
    user: alice
    key_path: ~/.ssh/id_ed25519

default_host: myserver
```

这就是完整的最简配置。保存文件。

> **关于主机标签的说明：** `myserver` 是你自己取的名字——它会出现在 Claude Code 调用的工具名称中（例如 `mcp__remote-myserver__Read`）。请使用简短且对 slug 友好的名称（字母、数字、连字符）。本教程通篇使用 `myserver`，遇到时请替换为你自己的名称。

---

## 第三步 — 测试连接

运行内置测试，验证 remote-mcp 能够连接到你的主机，并且所有工具都通过快速健全性检查。

```bash
python -m remote_mcp --host myserver --test
```

你应该看到：

```
Connecting to myserver (alice@your-host.example.com)... OK
Testing exec channel... OK
Testing SFTP... OK
Testing bash session... OK
Testing Read... OK
Testing Write... OK
Testing Edit... OK
Testing Glob... OK
Testing Grep... OK

Connected to myserver (alice@your-host.example.com). All tools: OK
```

看到 `All tools: OK`，说明连接正常，所有工具路径均可用。你已经准备好向 Claude Code 注册了。

如果出现错误，请在此停下来。先从同一个终端会话中确认 `ssh alice@your-host.example.com` 可以正常运行，再继续操作。常见的修复方法请参阅[故障排查指南](../how-to/debug-mcp-not-appearing.md)。

---

## 第四步 — 向 Claude Code 注册

运行 `claude mcp add` 将此主机注册为 MCP 服务器。`--global` 标志使其在所有 Claude Code 项目中均可用。

```bash
claude mcp add --global remote-myserver -- python -m remote_mcp --host myserver
```

你应该看到：

```
MCP server "remote-myserver" added to global config.
```

只需这一条命令。Claude Code 会保存服务器条目，并在你下次打开 Claude Code 时自动启动 remote-mcp 进程。

---

## 第五步 — 重启 Claude Code

完全关闭 Claude Code 并重新打开。工具列表在启动时加载——正在运行的 Claude Code 会话不会自动识别新注册的 MCP 服务器。

重启后，打开任意 Claude Code 项目。在工具选择器中（或通过输入斜杠命令），你可以验证工具已成功注册：

```
/tools
```

滚动列表，直到看到以 `mcp__remote-myserver__` 开头的条目。你应该能找到全部十个：

```
mcp__remote-myserver__Read
mcp__remote-myserver__Write
mcp__remote-myserver__Edit
mcp__remote-myserver__MultiEdit
mcp__remote-myserver__MultiRead
mcp__remote-myserver__FileStat
mcp__remote-myserver__Bash
mcp__remote-myserver__Glob
mcp__remote-myserver__Grep
mcp__remote-myserver__Feedback
```

看到这十个工具，说明 Claude Code 已成功加载服务器。

---

## 第六步 — 第一次远程工具调用

现在我们来让 Claude Code 使用一个远程工具。打开一个新对话，输入以下内容：

```
Use the remote tools for myserver to read /etc/hostname on the remote host and tell me what it says.
```

Claude Code 将调用 `mcp__remote-myserver__Read`。你可以在对话中看到工具调用的出现。代理的工具调用看起来像这样：

```
mcp__remote-myserver__Read
  file_path: /etc/hostname
```

返回给代理的工具结果看起来像这样：

```
     1	your-host.example.com
```

代理随后会回复类似这样的内容：

```
The remote host's hostname is your-host.example.com.
```

实际的主机名取决于你服务器上 `/etc/hostname` 的内容。如果你看到了这一完整交互——工具调用、带行号的结果、以及代理的回复——那么你的第一次远程会话就完成了。

---

## 刚才发生了什么

在这六个步骤中，你：

1. 将 remote-mcp 作为本地 Python 包安装。
2. 告诉它要连接到哪台远程主机。
3. 通过 SSH 验证了每个工具的端到端可用性。
4. 注册了服务器，使 Claude Code 能够启动它。
5. 重启后工具完成加载。
6. 亲眼看到代理调用了一个远程工具并读取了一个真实文件。

remote-mcp 进程在本地运行，通过 stdio 与 Claude Code 通信（使用 MCP 协议），并通过 SSH 与你的远程主机通信。Claude Code 并不知道也不在意文件是远程的——它调用 `Read`，得到带行号的返回内容，与使用原生工具完全相同。

---

## 接下来做什么

**充分利用这些工具。** 将本仓库根目录中的 `CLAUDE.md.fragment.md` 复制到你远程项目的 `CLAUDE.md` 中。它能教会代理带宽感知的使用模式——用 MultiRead 批量读取文件、用带上下文行的 Grep 替代"先 Grep 再 Read"、用 `run_in_background` 在后台运行长时间构建任务。没有它，代理也能正确使用工具，但不够高效。

**理解系统原理。** 阅读[概念说明：架构概览](../explanation/architecture.md)，建立清晰的心智模型——了解哪些进程在运行、数据通过哪些协议传输，以及持久化 bash 会话存在的原因。

**完成更具体的任务。** [操作指南](../how-to/README.md)涵盖了多主机配置、通过堡垒机进行 ProxyJump、针对慢速网络的调优、连接断开后的恢复等更多内容。
