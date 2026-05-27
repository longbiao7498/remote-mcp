# 配置 Schema

> English version: [config-schema.md](./config-schema.md)

配置文件为 YAML 格式。默认路径：`~/.config/remote-mcp/config.yaml`。可通过 CLI 的 `--config <path>` 覆盖。

## 顶层字段

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `hosts` | map | 是 | — | 主机名到各主机配置的映射。键即 `--host` 参数的值。 |
| `default_host` | string | 否 | `null` | 省略 `--host` 时使用的主机名（CLI 中尚未接入；保留供未来使用）。 |
| `feedback_path` | string | 否 | `~/.local/share/remote-mcp/feedback.jsonl` | Feedback 工具输出文件的本地文件系统路径。 |

## 每主机字段

`hosts` 下的每个键为逻辑主机名（用于 `--host` 和 `[WARNING]` 消息）。其值为包含以下字段的映射。

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `hostname` | string | 是 | — | 远程主机的 DNS 名称或 IP 地址。 |
| `user` | string | 是 | — | SSH 用户名。 |
| `port` | integer | 否 | `22` | SSH 端口。 |
| `key_path` | string | 否 | `null` | 私钥文件路径。`~` 在连接时展开，而非在解析时展开。若省略，paramiko 使用默认密钥搜索（agent + `~/.ssh/id_*`）。 |
| `password` | string | 否 | `null` | SSH 密码。在实际使用中与 `key_path` 互斥；若两者均设置，`key_path` 优先（paramiko 行为）。 |
| `jump_host` | string | 否 | `null` | 用作 ProxyJump/堡垒机的另一个 `hosts` 条目名称。先连接跳板主机，再通过其 `direct-tcpip` 通道作为目标连接的 socket。 |
| `connect_timeout` | float | 否 | `10.0` | 等待 TCP 连接建立的超时秒数。同时作用于跳板和目标连接。 |
| `keepalive_interval` | integer | 否 | `30` | SSH keepalive 包之间的间隔秒数（`Transport.set_keepalive`）。设为 `0` 可禁用。用于防止 NAT/VPN 因空闲超时断开连接。 |
| `compression` | boolean | 否 | `true` | 启用 SSH 传输层压缩。 |
| `bash_timeout_default` | integer | 否 | `120` | Bash 工具前台命令在调用方未指定 `timeout` 时的默认超时秒数。 |
| `glob_output_limit` | integer | 否 | `1000` | Glob 工具在截断前返回的最大文件路径数。 |
| `read_size_cap` | integer | 否 | `262144` | Read 和 MultiRead 返回的最大字节数（默认 256 KB），超出时截断。 |
| `bash_output_cap` | integer | 否 | `102400` | Bash 返回的最大字节数（默认 100 KB），超出时截断。 |
| `transfer_size_cap` | int | 否 | 104857600 (100 MB) | `Upload` 或 `Download` 单文件最大传输字节数。超过会返回 `Error:` 字符串，并附上可直接粘贴的 `Bash + scp` 命令。如确实需要传更大的文件而不想切到 scp，调高此值。 |

## 最简示例

```yaml
hosts:
  prod:
    hostname: 192.0.2.10
    user: alice
```

## 完整示例

```yaml
default_host: dev

feedback_path: ~/.local/share/remote-mcp/feedback.jsonl

hosts:
  bastion:
    hostname: bastion.example.com
    user: ops
    port: 22
    key_path: ~/.ssh/id_ed25519_bastion
    connect_timeout: 10.0
    keepalive_interval: 30
    compression: true

  dev:
    hostname: dev-internal.example.com
    user: alice
    port: 22
    key_path: ~/.ssh/id_ed25519
    jump_host: bastion
    connect_timeout: 15.0
    keepalive_interval: 20
    compression: true
    bash_timeout_default: 180
    glob_output_limit: 2000
    read_size_cap: 524288
    bash_output_cap: 204800

  prod:
    hostname: prod.example.com
    user: deploy
    password: "s3cr3t"
    port: 2222
    connect_timeout: 10.0
    keepalive_interval: 30
    compression: false
    bash_timeout_default: 120
    glob_output_limit: 1000
    read_size_cap: 262144
    bash_output_cap: 102400
```

## 文件格式与解析

- 文件使用 `yaml.safe_load` 解析。PyYAML 严格模式：不允许任意 Python 对象标签。
- `key_path` 中包含 `~` 的值通过 `os.path.expanduser` 在连接时展开，而非在解析时展开。存储的字符串始终是文件中的原始值。
- `hosts` 必须存在且非空，服务器才能找到任何主机。`hosts` 键缺失或为空在解析时不报错，但会在启动时引发 `KeyError`。
- 主机条目下的未知字段会在解析时引发 `TypeError`（Python dataclass 拒绝意外的关键字参数）。
- `feedback_path` 的默认值在运行时经 `~` 展开后解析为绝对路径。
- 所有数字字段（`port`、`keepalive_interval`、`bash_timeout_default` 等）在 YAML 中必须为整数；浮点数会引发 `TypeError`。
- `connect_timeout` 是唯一的例外：其类型为 `float`，YAML 中 `10` 和 `10.0` 均可接受。
