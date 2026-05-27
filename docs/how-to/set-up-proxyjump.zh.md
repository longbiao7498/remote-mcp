# 设置 ProxyJump（堡垒机）

> English version: [set-up-proxyjump.md](./set-up-proxyjump.md)

## 适用场景

目标主机无法从你的机器直接访问——必须先通过堡垒机（跳板机）建立隧道。当 `ssh user@target` 失败但 `ssh -J user@bastion user@target` 成功时，本指南适用。

## 前置条件

- 对堡垒机和目标主机均有 SSH 密钥访问权限
- 已安装 remote-mcp（`pip install -e .`）
- 堡垒机已注册为独立的主机条目（需要验证连通性，但不需要完整的 MCP 注册）

## 步骤

1. **在 `~/.config/remote-mcp/config.yaml` 中定义两台主机**

   堡垒机必须有自己的命名条目。目标主机通过 `jump_host:` 按名称引用堡垒机。

   ```yaml
   hosts:
     jump:
       hostname: jump.example.com
       user: ops
       port: 2222
       key_path: ~/.ssh/jump_key

     prod:
       hostname: 10.0.0.50        # only reachable from jump
       user: ubuntu
       key_path: ~/.ssh/id_ed25519
       jump_host: jump            # must match the key above exactly

   default_host: prod
   ```

   `jump_host` 填写主机**名称**（配置键），而非主机名或 IP 地址。

2. **注册前先验证连通性**

   ```bash
   python -m remote_mcp --host prod --test
   ```

   remote-mcp 会在跳板机传输层上打开隧道通道，再通过该通道连接目标传输层。如果测试通过，ProxyJump 已正常工作。

3. **将目标主机注册到 Claude Code**

   只注册目标主机——不注册堡垒机。堡垒机作为隧道透明使用。

   ```bash
   claude mcp add --global remote-prod -- python -m remote_mcp --host prod
   ```

4. **重启 Claude Code**

## 验证

在 Claude Code 中：

```
mcp__remote-prod__Bash("hostname && ip route")
```

结果应显示目标主机的主机名和其内网路由——而非堡垒机的。

## 常见问题排查

- **`--test` 在"Connecting to jump..."处挂起** — 确认堡垒机可直接访问：`ssh -p 2222 ops@jump.example.com`。检查跳板机条目的 `port` 和 `key_path`。
- **`--test` 通过了堡垒机但目标主机失败** — `prod` 使用的密钥可能未安装在目标主机上。注意 `key_path` 从本地机器读取并通过隧道转发；不需要 agent 转发。
- **连接反复断线** — 隧道增加了第二条 keepalive 路径。将目标主机条目的 `keepalive_interval` 调低至 15，并参见[针对慢速网络调优](./tune-for-slow-networks.md)。
