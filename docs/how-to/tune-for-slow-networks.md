# Tune for slow or lossy networks

> 中文版本：[tune-for-slow-networks.zh.md](./tune-for-slow-networks.zh.md)

## When to use this guide

You are on a high-latency link (RTT > 200 ms), limited bandwidth (< 1 MB/s), or a VPN that drops idle connections. Symptoms: tool calls feel sluggish, commands time out more often than expected, or the agent sees repeated `[WARNING] SSH connection ... was lost` messages.

## What you need first

- A working host entry in `~/.config/remote-mcp/config.yaml`
- The default values to compare against (shown in parentheses below)

## Steps

1. **Lower `keepalive_interval` to survive aggressive idle timeouts**

   The default (30 s) is fine for most corporate VPNs. If your VPN cuts idle TCP connections at 60 s or less, set it lower:

   ```yaml
   hosts:
     prod:
       hostname: 10.0.0.50
       user: ubuntu
       key_path: ~/.ssh/id_ed25519
       keepalive_interval: 15      # seconds; must be less than VPN idle timeout
   ```

   Setting this too low (< 10 s) wastes bandwidth on keepalive packets without further benefit. 15 s is a safe floor for most environments.

2. **Confirm compression is on (default: true)**

   SSH-level compression is enabled by default and gives 3–10× reduction for text (source code, logs, config). Only disable it if you are transferring already-compressed data (tarballs, binaries) and profiling shows it costs CPU:

   ```yaml
       compression: true           # keep this; only set false if you've profiled it
   ```

3. **Raise `bash_timeout_default` for slow remote commands**

   The default (120 s) applies to every foreground `Bash` call unless the agent overrides it per-call. On a slow remote host, builds and installs can exceed this:

   ```yaml
       bash_timeout_default: 300   # seconds; raise to match your longest expected command
   ```

   For commands that routinely take longer than a few minutes, use `run_in_background=true` instead of raising this further — see [Run long background jobs](./run-long-background-jobs.md).

4. **Cap `bash_output_cap` to avoid flooding a slow link**

   The default (100 KB ≈ 102 400 bytes) caps how much output a single `Bash` call returns. On a 100 KB/s link this is already 1 second of transfer. If large outputs are causing timeouts, lower it:

   ```yaml
       bash_output_cap: 51200      # 50 KB; excess is truncated with a note
   ```

5. **Raise `glob_output_limit` only if needed**

   The default (1 000 entries) is appropriate for most searches. Raise it only if Glob is silently cutting off results you need:

   ```yaml
       glob_output_limit: 2000
   ```

   On slow links, prefer targeted Grep over broad Glob when possible.

**Complete example for a slow-link host:**

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

## Verification

After saving config, restart the MCP server (restart Claude Code or kill and reopen the session):

```bash
python -m remote_mcp --host remote-slow --test
```

Then run a command that previously timed out. If the `[WARNING] SSH connection ... was lost` message has stopped appearing, `keepalive_interval` is now below your VPN's idle timeout.

## When this doesn't work

- **Repeated reconnect warnings persist** — the underlying link may be too unstable for auto-reconnect to help. See [Recover after a connection drop](./recover-from-disconnect.md).
- **Bash still times out even with a raised `bash_timeout_default`** — switch the offending command to `run_in_background=true`; see [Run long background jobs](./run-long-background-jobs.md).
- **Output is still being truncated** — the agent can pass an explicit `timeout=` per call; alternatively raise `bash_output_cap`, accepting the transfer cost.
