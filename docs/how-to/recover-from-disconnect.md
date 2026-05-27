# Recover after a connection drop

> 中文版本：[recover-from-disconnect.zh.md](./recover-from-disconnect.zh.md)

## When to use this guide

The agent's last tool result was prefixed with:

```
[WARNING] SSH connection to <host> was lost and has been re-established. The
remote bash session has been reset: working directory is now $HOME, all
environment variables set in previous commands are lost. Use absolute paths
and re-run any necessary setup commands.
```

The connection has already been automatically restored. This guide tells you what to do next.

## What you need first

- The list of any `cd` or `export` commands that were run earlier in this session (check the conversation history)

## Steps

1. **Do not panic — the connection is already live again**

   The warning is emitted on the first tool call after a successful auto-reconnect. The SSH transport and bash session are fresh. The tool result that follows the warning is from the new session, not from a stale one.

2. **Confirm the current directory**

   The bash session resets to `$HOME` after reconnect. Ask the agent to confirm where it is now:

   ```
   Bash("pwd && echo $HOME")
   ```

3. **Re-establish working directory and environment**

   If previous work depended on a specific directory:

   ```
   Bash("cd /opt/app && pwd")
   ```

   If previous work required environment variables (e.g., `PYTHONPATH`, `VIRTUAL_ENV`):

   ```
   Bash("export PYTHONPATH=/opt/app/src && source /opt/app/.venv/bin/activate")
   ```

   Use **absolute paths** for all subsequent file operations — the cwd cannot be assumed.

4. **Check background jobs started before the disconnect**

   Background jobs launched with `run_in_background=true` are unaffected by the reconnect — they run in their own process group on the remote host. Verify they are still running:

   ```
   Bash("kill -0 <pid> && echo running || echo done")
   ```

   See [Run long background jobs](./run-long-background-jobs.md) for the full polling workflow.

5. **If the warning repeats on every call, stabilize the connection first**

   Repeated warnings mean the underlying link is dropping frequently. Lower `keepalive_interval` in config (e.g., to 15 s) and restart the MCP server before continuing work:

   ```yaml
   hosts:
     prod:
       keepalive_interval: 15
   ```

   See [Tune for slow networks](./tune-for-slow-networks.md).

## Verification

After re-running setup commands, run a simple check:

```
Bash("pwd && echo $PYTHONPATH")
```

Confirm the directory and variables are as expected before continuing the task.

## When this doesn't work

- **Next tool call returns `Error: SSH connection lost and reconnect failed`** — the auto-reconnect itself failed. Check network connectivity to the host manually (`ssh user@host`). Fix the SSH problem and then retry any tool call — remote-mcp will attempt reconnect again on the next call.
- **Warning appears on every single tool call** — the keepalive interval is above your VPN's idle timeout. See [Tune for slow networks](./tune-for-slow-networks.md).
- **Host is behind a bastion and reconnect keeps failing** — verify the bastion itself is reachable. If the bastion dropped too, both connections must come back before remote-mcp can reconnect. See [Set up ProxyJump](./set-up-proxyjump.md).
