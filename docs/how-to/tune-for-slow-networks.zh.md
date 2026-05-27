# 针对慢速或不稳定网络调优

> English version: [tune-for-slow-networks.md](./tune-for-slow-networks.md)

## 适用场景

你处于高延迟链路（RTT > 200 ms）、带宽受限（< 1 MB/s）或 VPN 会断开空闲连接的网络环境。症状：工具调用感觉迟缓、命令超时频率高于预期，或 agent 反复看到 `[WARNING] SSH connection ... was lost` 消息。

## 前置条件

- `~/.config/remote-mcp/config.yaml` 中已有可用的主机条目
- 用于对比的默认值（以下括号内标注）

## 步骤

1. **调低 `keepalive_interval` 以应对激进的空闲超时**

   默认值（30 秒）对大多数企业 VPN 已足够。如果你的 VPN 在 60 秒或更短时间内切断空闲 TCP 连接，请调低：

   ```yaml
   hosts:
     prod:
       hostname: 10.0.0.50
       user: ubuntu
       key_path: ~/.ssh/id_ed25519
       keepalive_interval: 15      # seconds; must be less than VPN idle timeout
   ```

   设置过低（< 10 秒）会在 keepalive 包上浪费带宽而没有额外收益。15 秒是大多数环境的安全下限。

2. **确认压缩已开启（默认：true）**

   SSH 级别压缩默认启用，对文本（源代码、日志、配置）可实现 3–10 倍压缩比。只有在传输已压缩数据（tarball、二进制文件）且分析显示 CPU 开销成为瓶颈时才关闭：

   ```yaml
       compression: true           # keep this; only set false if you've profiled it
   ```

3. **为慢速远程命令提高 `bash_timeout_default`**

   默认值（120 秒）适用于每次前台 `Bash` 调用，除非 agent 针对单次调用显式覆盖。在慢速远程主机上，构建和安装可能超出这个时间：

   ```yaml
       bash_timeout_default: 300   # seconds; raise to match your longest expected command
   ```

   对于常规耗时超过几分钟的命令，使用 `run_in_background=true` 而非继续提高此值——参见[运行长时间后台任务](./run-long-background-jobs.md)。

4. **设置 `bash_output_cap` 上限以避免慢速链路被输出淹没**

   默认值（100 KB ≈ 102 400 字节）限制单次 `Bash` 调用返回的输出量。在 100 KB/s 的链路上这已经意味着 1 秒的传输时间。如果大量输出导致超时，调低此值：

   ```yaml
       bash_output_cap: 51200      # 50 KB; excess is truncated with a note
   ```

5. **仅在必要时提高 `glob_output_limit`**

   默认值（1 000 条）对大多数搜索已够用。只有当 Glob 静默截断了你需要的结果时才调高：

   ```yaml
       glob_output_limit: 2000
   ```

   在慢速链路上，尽量用有针对性的 Grep 替代宽泛的 Glob。

**慢速链路主机的完整示例配置：**

```yaml
hosts:
  remote-slow:
    hostname: 10.0.0.50
    user: ubuntu
    key_path: ~/.ssh/id_ed25519
    keepalive_interval: 15
    compression: true
    bash_timeout_default: 300
    bash_output_cap: 51200
    glob_output_limit: 1000
```

## 验证

保存配置后，重启 MCP 服务器（重启 Claude Code 或关闭并重新打开会话）：

```bash
python -m remote_mcp --host remote-slow --test
```

然后运行之前超时的命令。如果 `[WARNING] SSH connection ... was lost` 消息不再出现，说明 `keepalive_interval` 现在已低于 VPN 的空闲超时时间。

## 常见问题排查

- **重连警告持续出现** — 底层链路可能过于不稳定，自动重连无法解决。参见[连接断开后恢复](./recover-from-disconnect.md)。
- **即使提高了 `bash_timeout_default`，Bash 仍然超时** — 将相关命令改为 `run_in_background=true`；参见[运行长时间后台任务](./run-long-background-jobs.md)。
- **输出仍被截断** — agent 可以针对单次调用传入显式的 `timeout=`；或者提高 `bash_output_cap`，接受相应的传输开销。
