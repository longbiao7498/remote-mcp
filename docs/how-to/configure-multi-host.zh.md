# 配置多个远程主机

> English version: [configure-multi-host.md](./configure-multi-host.md)

## 适用场景

你需要 Claude Code 在同一个会话中操作两台或三台不同的服务器。每台主机对应独立的 MCP 服务器条目和独立的工具集。

## 前置条件

- 已安装 remote-mcp（`pip install -e .`）
- 每台主机均已配置 SSH 密钥访问
- 熟悉单主机配置（参见[教程](../tutorial/first-remote-session.md)）

## 步骤

1. **将每台主机添加到 `~/.config/remote-mcp/config.yaml`**

   ```yaml
   hosts:
     prod:
       hostname: 192.168.1.100
       user: ubuntu
       key_path: ~/.ssh/id_ed25519

     gpu:
       hostname: 10.0.0.60
       user: longbiao
       key_path: ~/.ssh/id_ed25519

     staging:
       hostname: 10.0.0.70
       user: ubuntu
       key_path: ~/.ssh/id_ed25519

   default_host: prod
   ```

   `hosts:` 下的每个顶层键即为传递给 `--host` 的主机名。

2. **将每台主机注册为独立的 MCP 服务器**

   ```bash
   claude mcp add --global remote-prod    -- python -m remote_mcp --host prod
   claude mcp add --global remote-gpu     -- python -m remote_mcp --host gpu
   claude mcp add --global remote-staging -- python -m remote_mcp --host staging
   ```

   前缀（`remote-prod`、`remote-gpu` 等）决定了 Claude Code 暴露的工具命名空间。

3. **重启 Claude Code**

   工具列表在启动时加载。重启后你将看到：

   ```
   mcp__remote-prod__Read     mcp__remote-prod__Bash     ...
   mcp__remote-gpu__Read      mcp__remote-gpu__Bash      ...
   mcp__remote-staging__Read  mcp__remote-staging__Bash  ...
   ```

4. **开始工作前对每台主机做冒烟测试**

   ```bash
   python -m remote_mcp --host prod    --test
   python -m remote_mcp --host gpu     --test
   python -m remote_mcp --host staging --test
   ```

   每条命令的预期输出：`Connected to <host> (<user>@<hostname>). All tools: OK`

## 验证

在 Claude Code 中，让 agent 执行：

```
mcp__remote-prod__Bash("hostname")
mcp__remote-gpu__Bash("hostname")
```

每条结果以 `[host=prod cwd=...]` 或 `[host=gpu cwd=...]` 开头。确认主机名与预期一致。

## 常见问题排查

- **重启后工具未出现** — 参见[调试：MCP 工具未出现在 Claude Code 中](./debug-mcp-not-appearing.md)。
- **某台主机可以连接但另一台不行** — 对失败的主机运行 `python -m remote_mcp --host <name> --test`，先修复 SSH 错误再重新注册。
- **主机位于堡垒机之后** — 在添加主机条目之前，先参见[设置 ProxyJump](./set-up-proxyjump.md)。
