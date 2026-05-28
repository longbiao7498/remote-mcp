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
       hostname: prod.example.com
       user: deploy
       key_path: ~/.ssh/id_ed25519
       cwd: /opt/myapp

     staging:
       hostname: staging.example.com
       user: deploy
       key_path: ~/.ssh/id_ed25519
       cwd: ~/work/staging

     gpu:
       hostname: gpu.cluster.example.com
       user: researcher
       key_path: ~/.ssh/id_ed25519
       cwd: ~/scratch/current-experiment

   default_host: prod
   ```

   `hosts:` 下的每个顶层键即为传递给 `--host` 的主机名。可选的 `cwd` 字段为所有工具的相对路径提供锚点——`Read("config.yaml")` 会解析为 `<cwd>/config.yaml`。省略则默认为远程 `$HOME`。接受的格式：`/绝对路径`、`~` 或 `~/子路径`；波浪号在连接时展开，路径存在性通过 SFTP stat 验证（路径不存在则启动时报错）。

2. **将每台主机注册为独立的 MCP 服务器**

   ```bash
   claude mcp add --scope user remote-prod    -- python -m remote_mcp --host prod
   claude mcp add --scope user remote-staging -- python -m remote_mcp --host staging
   claude mcp add --scope user remote-gpu     -- python -m remote_mcp --host gpu
   ```

   **每行有两个你自己选的 token，外加一堆固定 CLI 语法。** 分开看：

   ```
   claude mcp add --scope user  <NAMESPACE>  --  python -m remote_mcp --host  <HOST-KEY>
   └── 固定 Claude Code ──┘└── 你选 ──┘   ↑   └── 固定 remote-mcp ──────┘└── 你选 ──┘
                                        分隔符
   ```

   - **`<NAMESPACE>`** —— Claude Code 给这个 MCP 服务器起的标签。它会成为 agent 看到的**工具前缀**：`mcp__<NAMESPACE>__Read` 等。后续 `claude mcp remove <NAMESPACE>`、`claude mcp list` 也用它。
   - **`<HOST-KEY>`** —— 第 1 步 `config.yaml` 里 `hosts:` 块下的 key。决定 SSH 到哪台远程。

   其余部分（`claude mcp add`、`--scope user`、`--`、`python -m remote_mcp`、`--host`）都是**固定 CLI 语法**——照抄。

   两个**你选**的 token 互相独立。你*可以*写成 `claude mcp add --scope user pixie-dust -- python -m remote_mcp --host prod`，agent 看到的就是 `mcp__pixie-dust__Read` 操作 `prod` 主机。**推荐用上面的 `remote-<HOST-KEY>` 同名约定**——看到 `mcp__remote-prod__Bash` 就一眼能看出操作哪台。除非有特别理由，否则保持这个习惯。

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
