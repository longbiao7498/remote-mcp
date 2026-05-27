# 连接断开后恢复

> English version: [recover-from-disconnect.md](./recover-from-disconnect.md)

## 适用场景

agent 上一次工具调用的结果以如下内容开头：

```
[WARNING] SSH connection to <host> was lost and has been re-established. The
remote bash session has been reset: working directory is now $HOME, all
environment variables set in previous commands are lost. Use absolute paths
and re-run any necessary setup commands.
```

连接已自动恢复。本指南告诉你接下来该做什么。

## 前置条件

- 本次会话中执行过的 `cd` 或 `export` 命令列表（查看对话历史）

## 步骤

1. **不必慌张——连接已经恢复**

   警告在成功自动重连后的第一次工具调用时发出。SSH 传输层和 bash 会话均已重新建立。警告之后的工具结果来自新会话，而非旧的陈旧状态。

2. **确认当前目录**

   重连后 bash 会话重置到 `$HOME`。让 agent 确认当前所在位置：

   ```
   Bash("pwd && echo $HOME")
   ```

3. **恢复工作目录和环境变量**

   如果之前的工作依赖特定目录：

   ```
   Bash("cd /opt/app && pwd")
   ```

   如果之前的工作需要环境变量（如 `PYTHONPATH`、`VIRTUAL_ENV`）：

   ```
   Bash("export PYTHONPATH=/opt/app/src && source /opt/app/.venv/bin/activate")
   ```

   后续所有文件操作请使用**绝对路径**——当前目录不可假设。

4. **检查断线前启动的后台任务**

   通过 `run_in_background=true` 启动的后台任务不受重连影响——它们在远程主机上以独立的进程组运行。验证它们是否仍在运行：

   ```
   Bash("kill -0 <pid> && echo running || echo done")
   ```

   完整的轮询工作流参见[运行长时间后台任务](./run-long-background-jobs.md)。

5. **如果警告在每次调用时都出现，先稳定连接**

   反复出现警告说明底层链路频繁断线。在继续工作前，将配置中的 `keepalive_interval` 调低（例如调为 15 秒）并重启 MCP 服务器：

   ```yaml
   hosts:
     prod:
       keepalive_interval: 15
   ```

   参见[针对慢速网络调优](./tune-for-slow-networks.md)。

## 验证

重新执行配置命令后，运行简单检查：

```
Bash("pwd && echo $PYTHONPATH")
```

在继续任务前，确认目录和变量均符合预期。

## 常见问题排查

- **下一次工具调用返回 `Error: SSH connection lost and reconnect failed`** — 自动重连本身失败了。手动检查主机的网络连通性（`ssh user@host`）。修复 SSH 问题后重试任何工具调用——remote-mcp 会在下次调用时再次尝试重连。
- **每次工具调用都出现警告** — keepalive 间隔超过了 VPN 的空闲超时时间。参见[针对慢速网络调优](./tune-for-slow-networks.md)。
- **主机位于堡垒机之后且重连持续失败** — 验证堡垒机本身是否可达。如果堡垒机也断线了，两个连接都必须恢复后 remote-mcp 才能重连。参见[设置 ProxyJump](./set-up-proxyjump.md)。
