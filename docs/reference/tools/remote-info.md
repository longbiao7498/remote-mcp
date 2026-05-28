# RemoteInfo

> 中文版本：[remote-info.zh.md](./remote-info.zh.md)

Return the connection's **configured** identity — host label, user, hostname, port, jump_host. **No SSH call is made**; values come directly from `~/.config/remote-mcp/config.yaml`.

## Why this exists (not what — see Behavior notes)

In VPN scenarios, the IP the remote reports via `hostname -I` is an internal-network IP that does NOT match the IP the client uses to reach it. An agent asking "which host am I really operating on?" cannot trust `Bash("hostname -I")`. This tool returns the authoritative client-side answer.

## Schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## Parameters

None.

## Returns

A string of 6 lines, one per field, in `key=value` format:

```
host=<config-key>
user=<config-user>
hostname=<config-hostname>
port=<config-port>
jump_host=<config-jump-host or "none">
cwd=<configured-cwd>
```

- `cwd=<configured-cwd>`: the remote working dir all relative-path tool calls resolve against (~ already expanded).

Example:

```
host=prod
user=ubuntu
hostname=10.0.0.50
port=22
jump_host=bastion
cwd=/home/ubuntu/project
```

## Error wording

None — RemoteInfo cannot fail (it reads in-memory config that's already loaded; if config loading had failed, the MCP server wouldn't have started).

## Behavior notes

- Pure local lookup. Zero SSH traffic. Returns instantly.
- Values match what `connection.py` uses to build the paramiko `Transport`: the `hostname` is what we *connect to*, not what the remote *reports*.
- If you DO want the remote's self-reported identity (kernel, IPs as seen from inside), use `Bash("whoami && hostname && hostname -I && uname -a")` — but in VPN scenarios that answer may differ from `RemoteInfo`'s, and `RemoteInfo` is the connection-truth.
- The `jump_host` field is the name of another `hosts:` entry in `config.yaml`, or `none` if no jump is configured. RemoteInfo does NOT recursively expand the jump host's details — get them with a second call after switching connection.

## Bandwidth/latency profile

- **Transfer size:** zero bytes over SSH.
- **Round-trips:** zero.
- **Latency:** microseconds.

## See also

- [Configuration schema](../config-schema.md) — the source these fields are read from
- [Bash](./bash.md) — for asking the remote its self-reported identity
- [Explanation: multi-host model](../../explanation/multi-host-model.md) — why the `[host=X]` prefix is the config name, not the IP
- Spec — *not in spec; added in v0.1.1*
