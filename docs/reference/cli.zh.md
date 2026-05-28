# CLI

> English version: [cli.md](./cli.md)

## 概要

```
python -m remote_mcp --host <name> [--config <path>] [--cwd <path>] [--test]
```

## 参数

| 名称 | 必填 | 默认值 | 描述 |
|------|------|--------|------|
| `--host <name>` | 是 | — | 要连接的逻辑主机名。必须与配置文件中 `hosts` 下的某个键匹配。 |
| `--config <path>` | 否 | `~/.config/remote-mcp/config.yaml` | YAML 配置文件的路径。`~` 会被展开。 |
| `--cwd <path>` | 否 | 远程 `$HOME` | 远程工作目录。详见下方 `--cwd` 说明。 |
| `--test` | 否 | false | 运行冒烟测试而非启动 MCP 服务器（详见下方"模式"说明）。 |

### `--cwd <path>`

远程工作目录。所有工具的相对路径均以此为基准解析。必须以 `/` 开头（绝对路径），或为 `~` / `~/...`（相对于远程用户的 `$HOME`——在连接时展开）。

- 覆盖 `config.yaml` 中 `hosts.<name>.cwd` 的值。
- 默认值：远程 `$HOME`（等同于 `--cwd ~`）。
- 配置的 cwd 会出现在每个工具的输出中（形如 `[host=X cwd=Y]`）以及 `RemoteInfo` 中。

示例：

```bash
python -m remote_mcp --host prod --cwd /opt/myapp
```

## 模式

### 普通模式（stdio MCP 服务器）

不带 `--test` 时，进程加载配置、解析跳板主机（如已配置），向指定主机建立 SSH 连接，然后通过 stdio 运行 MCP 服务器。进程阻塞，直到 stdio 流关闭（即 MCP 客户端——通常是 Claude Code——断开连接）。退出时关闭 SSH 连接。日志输出（如有）写入 stderr。

### --test（冒烟测试）

带 `--test` 时，进程加载配置，向指定主机建立 SSH 连接，通过单次 `exec` 通道在远程 shell 上运行 `echo OK`，将单行结果打印到 stdout 后退出。退出前关闭 SSH 连接。退出码 0 表示连接及基本 exec 均正常；退出码 1 表示连接成功但 echo 命令未产生预期输出。

成功时的示例输出：

```
Connected to dev (alice@dev-internal.example.com). All tools: OK
```

echo 响应异常时的示例输出：

```
Connected but echo failed: 'something unexpected\n'
```

连接失败（主机错误、认证错误、网络不可达）会以未处理异常的形式呈现，在 stderr 输出 Python 堆栈跟踪，退出码为 1。

## 退出码

| 代码 | 含义 |
|------|------|
| `0` | 正常退出。`--test` 模式下：连接和 echo 均成功。服务器模式下：服务器正常关闭。 |
| `1` | 错误。`--test` 模式下：连接成功但 echo 产生了非预期输出，或发生了异常。服务器模式下：启动失败（配置未找到、主机不在配置中、SSH 认证失败等）。 |

## 环境变量

以下环境变量由集成测试套件读取，服务器本身不使用。

| 变量 | 描述 |
|------|------|
| `RMCP_TEST_HOST` | 运行集成测试时使用的主机名（对应配置中的某个 `hosts` 条目）。 |
| `RMCP_TEST_CONFIG` | 集成测试期间使用的配置文件路径。未设置时默认为 `~/.config/remote-mcp/config.yaml`。 |
