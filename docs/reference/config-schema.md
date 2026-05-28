# Configuration schema

> 中文版本：[config-schema.zh.md](./config-schema.zh.md)

The configuration file is YAML. Default location: `~/.config/remote-mcp/config.yaml`. Override with `--config <path>` at the CLI.

## Top-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `hosts` | map | Yes | — | Map of host name to per-host configuration. Keys become the `--host` argument. |
| `default_host` | string | No | `null` | Host name used when `--host` is omitted (not yet wired in the CLI; reserved for future use). |
| `feedback_path` | string | No | `~/.local/share/remote-mcp/feedback.jsonl` | Local filesystem path to the Feedback tool output file. |

## Per-host fields

Each key under `hosts` is the logical host name (used in `--host` and in `[WARNING]` messages). The value is a mapping of the following fields.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `hostname` | string | Yes | — | DNS name or IP address of the remote host. |
| `user` | string | Yes | — | SSH username. |
| `port` | integer | No | `22` | SSH port. |
| `key_path` | string | No | `null` | Path to the private key file. `~` is expanded at connect time, not at parse time. If omitted, paramiko's default key search applies (agent + `~/.ssh/id_*`). |
| `password` | string | No | `null` | SSH password. Mutually exclusive with `key_path` in practice; if both are set, `key_path` takes precedence (paramiko behavior). |
| `jump_host` | string | No | `null` | Name of another entry in `hosts` to use as a ProxyJump/bastion. The jump host is connected first; a `direct-tcpip` channel through it is used as the socket for the target connection. |
| `connect_timeout` | float | No | `10.0` | Seconds to wait for the TCP connection to be established. Applied to both jump and target connections. |
| `keepalive_interval` | integer | No | `30` | Seconds between SSH keepalive packets (`Transport.set_keepalive`). Set to `0` to disable. Prevents idle-timeout disconnections behind NAT/VPN. |
| `compression` | boolean | No | `true` | Enable SSH transport-level compression. |
| `cwd` | string \| null | No | null (→ remote `$HOME`) | Remote working directory. Must be `/...` (absolute) or `~` / `~/...`. Validated at connect time (SFTP stat); bad cwd → MCP server fails to start. |
| `bash_timeout_default` | integer | No | `120` | Default timeout in seconds for Bash tool foreground commands when the caller does not specify `timeout`. |
| `glob_output_limit` | integer | No | `1000` | Maximum number of file paths returned by the Glob tool before truncation. |
| `read_size_cap` | integer | No | `262144` | Maximum bytes of output returned by Read and MultiRead before truncation (default 256 KB). |
| `bash_output_cap` | integer | No | `102400` | Maximum bytes of output returned by Bash before truncation (default 100 KB). |
| `transfer_size_cap` | int | No | 104857600 (100 MB) | Maximum file size in bytes that `Upload` or `Download` will transfer. Files larger than this return an `Error:` string that includes a ready-to-paste `Bash + scp` command. Raise this if you need larger transfers and don't want to switch to scp. |

## Minimal example

```yaml
hosts:
  prod:
    hostname: 192.0.2.10
    user: alice
```

## Full example

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

## File format and parsing

- The file is parsed with `yaml.safe_load`. PyYAML strict mode: no arbitrary Python object tags.
- `key_path` values containing `~` are expanded via `os.path.expanduser` at connect time, not at parse time. The stored string is always the raw value from the file.
- `hosts` must be present and non-empty for the server to find any host. A missing or empty `hosts` key is not an error at parse time but causes a `KeyError` at startup.
- Unknown fields under a host entry cause a `TypeError` at parse time (Python dataclass rejects unexpected keyword arguments).
- The `feedback_path` default resolves to an absolute path at runtime, after `~` expansion.
- All numeric fields (`port`, `keepalive_interval`, `bash_timeout_default`, etc.) must be integers in YAML; floats cause a `TypeError`.
- `connect_timeout` is the one exception: it is typed `float` and accepts both `10` and `10.0` in YAML.
