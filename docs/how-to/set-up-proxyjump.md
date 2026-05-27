# Set up ProxyJump (bastion host)

> 中文版本：[set-up-proxyjump.zh.md](./set-up-proxyjump.zh.md)

## When to use this guide

The target host is not directly reachable from your machine — you must tunnel through a bastion (jump box) first. This is the right guide when `ssh user@target` fails but `ssh -J user@bastion user@target` succeeds.

## What you need first

- SSH key access to both the bastion and the target host
- remote-mcp installed (`pip install -e .`)
- The bastion registered as its own host entry (it needs connectivity verification, not a full MCP registration)

## Steps

1. **Define both hosts in `~/.config/remote-mcp/config.yaml`**

   The bastion must be its own named entry. The target references it by that name via `jump_host:`.

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

   `jump_host` takes the host **name** (the config key), not a hostname or IP.

2. **Verify connectivity before registering**

   ```bash
   python -m remote_mcp --host prod --test
   ```

   remote-mcp opens the tunnel channel on the jump transport, then connects the target transport through it. If this passes, ProxyJump is working.

3. **Register the target host with Claude Code**

   Only register the target — not the bastion. The bastion is used transparently as a tunnel.

   ```bash
   claude mcp add --global remote-prod -- python -m remote_mcp --host prod
   ```

   > The first `remote-prod` is the **MCP server label** Claude Code uses for namespacing tools (you choose it). The `--host prod` token is the **`hosts:` key** in your `config.yaml` (must match). Everything else is fixed CLI syntax — see [Configure multiple remote hosts → step 2](./configure-multi-host.md#steps) for the full disambiguation.

4. **Restart Claude Code**

## Verification

In Claude Code:

```
mcp__remote-prod__Bash("hostname && ip route")
```

The result should show the target host's hostname and its internal network routes — not the bastion's.

## When this doesn't work

- **`--test` hangs at "Connecting to jump..."** — confirm the bastion is reachable directly: `ssh -p 2222 ops@jump.example.com`. Check `port` and `key_path` for the jump entry.
- **`--test` passes the bastion but fails the target** — the key used for `prod` may not be installed on the target. Note that `key_path` is read from your local machine and forwarded via the tunnel; agent forwarding is not required.
- **Connection drops repeatedly** — the tunnel adds a second keepalive path. Lower `keepalive_interval` on the target entry to 15 and see [Tune for slow networks](./tune-for-slow-networks.md).
