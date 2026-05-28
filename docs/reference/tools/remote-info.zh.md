# RemoteInfo

> English version: [remote-info.md](./remote-info.md)

返回**连接的已配置身份**——host 标签、用户名、主机名、端口、跳板主机。**不发任何 SSH 请求**；值直接来自 `~/.config/remote-mcp/config.yaml`。

## 为什么存在（不是"是什么"——见"行为说明"）

VPN 场景下，远程通过 `hostname -I` 报告的 IP 是内网 IP，**与客户端实际连接的 IP 不一致**。agent 想知道"我现在到底操作的是哪台主机？"时，不能信任 `Bash("hostname -I")` 的答案。本工具返回的就是客户端这一侧的权威答案。

## Schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## 参数

无。

## 返回值

6 行字符串，每行一个字段，`key=value` 格式：

```
host=<config-key>
user=<config-user>
hostname=<config-hostname>
port=<config-port>
jump_host=<config-jump-host or "none">
cwd=<configured-cwd>
```

- `cwd=<configured-cwd>`：所有相对路径工具调用解析时所依据的远程工作目录（~ 已展开）。

示例：

```
host=prod
user=ubuntu
hostname=10.0.0.50
port=22
jump_host=bastion
cwd=/home/ubuntu/project
```

## 错误措辞

无——RemoteInfo 不会失败（它读取内存中已加载的配置；如果配置加载失败，MCP 服务器根本就不会启动）。

## 行为说明

- 纯本地查询。零 SSH 流量。瞬时返回。
- 值与 `connection.py` 构建 paramiko `Transport` 用的是同一份：`hostname` 是我们**实际连接**的目标，而**不是**远程报告的。
- 如果你**确实**想要远程自己报告的身份（内核、内部 IP 等），用 `Bash("whoami && hostname && hostname -I && uname -a")`——但在 VPN 场景下这个结果可能跟 `RemoteInfo` 不一致，且 `RemoteInfo` 才是连接侧的真相。
- `jump_host` 字段是 `config.yaml` 中 `hosts:` 块的另一个 entry 名称，或 `none`（如果未配置跳板）。RemoteInfo **不**递归展开跳板主机的详情——需要的话切换连接后再调一次。

## 带宽特征

- **传输大小**：0 字节（不经过 SSH）。
- **往返次数**：0。
- **延迟**：微秒级。

## 相关

- [配置 schema](../config-schema.zh.md) —— 这些字段的来源
- [Bash](./bash.zh.md) —— 用于问远程它自己报告的身份
- [概念说明：多主机模型](../../explanation/multi-host-model.zh.md) —— 为什么 `[host=X]` 前缀是 config 名称而不是 IP
- Spec —— *不在 spec 中；v0.1.1 新增*
