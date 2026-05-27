# 调试：MCP 工具未出现在 Claude Code 中

> English version: [debug-mcp-not-appearing.md](./debug-mcp-not-appearing.md)

## 适用场景

你已运行 `claude mcp add` 并重启了 Claude Code，但 `mcp__remote-<host>__*` 系列工具均未出现。本指南按可能性从高到低依次列出诊断步骤。

## 前置条件

- 你执行过的确切 `claude mcp add` 命令（用于核对拼写）
- 可执行诊断命令的终端访问权限

## 步骤

1. **确认 MCP 服务器条目存在**

   ```bash
   claude mcp list
   ```

   查找类似 `remote-prod` 的条目。如果没有，说明 `claude mcp add` 命令未完成执行——重新运行：

   ```bash
   claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
   ```

   **如果条目在，但看到的工具名跟预期不同**（比如 `mcp__pixie-dust__Read` 而不是 `mcp__remote-prod__Read`），说明 **MCP 服务器标签**（`claude mcp add` 的第一个参数）跟你以为的不一样。这个标签——和 `--host` 参数是两回事——决定了工具命名空间。重命名的话先删再加：

   ```bash
   claude mcp remove pixie-dust    # 用 `claude mcp list` 看到的那个奇怪名字
   claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
   ```

   两个名字的完整辨析见 [配置多台远程主机 → 第 2 步](./configure-multi-host.zh.md#步骤)。

2. **验证服务器进程能正常启动**

   工具列表只有在 MCP 服务器进程正常启动后才会填充。手动运行：

   ```bash
   python -m remote_mcp --host prod
   ```

   正常情况下应挂起等待 stdio 输入（按 Ctrl-C 退出）。如果立即报错退出，问题出在启动阶段——先修复错误再继续。

   常见启动错误：

   | 错误信息 | 原因 | 修复方法 |
   |---------------|-------|-----|
   | `No module named remote_mcp` | Python 解释器不对 | 用 `python -m pip install -e .` 对齐 pip 和 python |
   | `Config file not found` | 配置文件缺失或路径错误 | 创建 `~/.config/remote-mcp/config.yaml` |
   | `Host 'prod' not found in config` | `--host` 拼写错误或缺少主机键 | 检查配置 YAML 键名是否匹配 |
   | `FileNotFoundError: ... key_path` | 密钥文件路径错误或文件不存在 | 验证配置中的 `key_path` 展开后是否正确 |

3. **单独测试 SSH 连接**

   ```bash
   python -m remote_mcp --host prod --test
   ```

   预期输出：`Connected to prod (ubuntu@192.168.1.100). All tools: OK`

   如果失败，先修复 SSH/配置问题。服务器无法连接时，工具不会出现。

4. **检查 `claude mcp add` 注册的是哪个 Python**

   Claude Code 完全按照注册时的命令启动进程。如果你用 `python` 注册，但正确的解释器是 `python3` 或虚拟环境路径，进程将静默失败。

   在 shell 中验证 `python` 解析到哪里：

   ```bash
   which python
   python --version
   ```

   如需修正，用完整路径重新注册：

   ```bash
   claude mcp remove remote-prod
   claude mcp add --scope user remote-prod -- /usr/bin/python3 -m remote_mcp --host prod
   ```

5. **完全重启 Claude Code**

   工具在启动时加载。"重启"必须是完整的退出并重新启动，而不是关闭再打开标签页。启动后等待 MCP 服务器初始化完成（几秒钟）再检查工具是否出现。

6. **用 debug 模式启动 Claude Code，实时看 MCP 服务器 stderr**

   从终端用 `--debug` 启动（或 `--debug mcp` 过滤只看 MCP 相关输出）：

   ```bash
   claude --debug mcp
   ```

   这会把 MCP 服务器的启动消息和 stderr 直接打到你的终端上。`remote-mcp` 启动时任何 Python 回溯都会在这里显现。（早期 Claude Code 有一个单独的 `--mcp-debug` 标志——现已弃用，并入 `--debug`。）

   仅要验证注册条目本身（不启动 Claude Code），从任意 shell 跑 `claude mcp list`——它会列出每个已注册服务器，附带 `✓ Connected` 或 `✗ Failed to connect` 状态指示，失败时会带一行原因。

## 验证

修复问题并重启后，在 Claude Code 中确认：

```
mcp__remote-prod__Bash("echo ok")
```

应返回 `[host=prod cwd=/home/ubuntu]\nok`。

## 常见问题排查

- **条目出现在 `claude mcp list` 中但仍无工具** — 进程已注册但在发送工具列表之前崩溃了。检查 Claude Code 的 MCP 日志文件（上方步骤 6）。
- **工具出现但调用报错** — 服务器在运行但 SSH 连接失败。重新运行 `python -m remote_mcp --host prod --test` 定位 SSH 问题。
- **在终端中正常但在 Claude Code 中不行** — Claude Code 可能使用不同的 `PATH` 或 `HOME`。如有需要，为解释器和 `--config` 均注册绝对路径。
