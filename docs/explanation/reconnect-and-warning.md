# Reconnect and the WARNING Protocol

> 中文版本：[reconnect-and-warning.zh.md](./reconnect-and-warning.zh.md)

An SSH connection to a remote host can drop for many reasons: VPN reconnection, firewall idle timeout, network blip, server restart. Remote-mcp handles this automatically — but the recovery is not silent. This document explains why automatic recovery requires an explicit warning, what the warning says and why each part matters, and what state the agent can and cannot rely on after a reconnect.

## Why silent recovery is forbidden

The tempting behavior is to reconnect quietly and let the agent continue as if nothing happened. This would be wrong, and importantly, the wrongness would be invisible until something breaks badly.

When the SSH connection drops, the entire state of the remote bash session is lost. The bash process on the remote host is dead. A new one starts after reconnect, and it starts fresh: working directory is `$HOME`, no environment variables from previous commands, no sourced files, no aliases. If the agent was three tool calls into a workflow that set up a Python virtualenv, exported a `DATABASE_URL`, and `cd`'d into `/opt/myapp`, all of that is gone.

An agent that doesn't know about the reconnect will continue issuing commands with the assumption that the previous context is intact. It might run `python -m pytest` expecting to be in the right directory, get a confusing error about missing files, and try to debug what appears to be a test failure rather than a context collapse. The failure mode is subtle and hard to diagnose.

Silent recovery trades a small immediate confusion (the warning) for a large potential confusion (mysteriously broken commands). This is not a trade worth making.

## The three-part WARNING structure

The warning text is a contract. When `SSHConnection._reconnected` is set after a successful reconnect, the next `call_tool()` invocation checks the flag, clears it, and prepends this warning to the tool result:

```
[WARNING] SSH connection to <host_name> was lost and has been re-established.
The remote bash session has been reset: working directory is now $HOME,
all environment variables set in previous commands are lost.
Use absolute paths and re-run any necessary setup commands.
```

Each of the three parts serves a specific purpose:

**"SSH connection to \<host_name\> was lost and has been re-established."** — This tells the agent what happened. In a multi-host session, the agent needs to know which host was affected. A vague "connection restored" message would leave it uncertain about whether `prod` or `gpu` lost state, which bash session needs re-initialization, and which previous commands might have failed. The host name makes the scope of the disruption unambiguous.

**"working directory is now $HOME, all environment variables set in previous commands are lost."** — This tells the agent what state was lost. The agent cannot assume anything from before the reconnect survives. Specifically: `cd` commands have no effect across a reconnect, `export FOO=bar` has no effect across a reconnect, `source .env` has no effect across a reconnect. These are the three most common sources of shell context that agents build up over a session. The warning names them explicitly so the agent can rebuild the right ones.

**"Use absolute paths and re-run any necessary setup commands."** — This tells the agent what to do. "Absolute paths" is the specific, actionable instruction for the cwd problem: if the agent was working in `/opt/myapp`, it should start using that path explicitly rather than assuming the bash session is still there. "Re-run setup commands" covers the environment variable problem.

All three parts are required. A warning that only says "connection was re-established" fails the second and third parts. A warning that explains what was lost but doesn't say what to do next is incomplete.

## What survives a reconnect and what doesn't

**Survives:**
- The `SSHConnection` object and its configuration (hostname, user, key path, keepalive settings)
- The host registration in Claude Code's tool namespace
- The configuration in `config.yaml`
- Any files written to the remote filesystem (writes went through SFTP to disk)

**Does not survive:**
- The bash session: cwd, all exported environment variables, sourced files, shell functions, aliases
- The SFTP client: it is re-initialized lazily after reconnect, which is transparent
- Any in-flight tool calls at the moment of the drop: these return an error (the connection was lost while the operation was in progress)
- Background processes started with `run_in_background=true`: these are children of the old bash session or descendants of `setsid` — if the host itself is still running, `setsid`-ed processes survive (they're in their own session), but the agent no longer has their PIDs in context and should check carefully before assuming they're still running

## If reconnect fails

If the automatic reconnect attempt fails, the tool result is:

```
Error: SSH connection to <host> lost and reconnect failed: <reason>
```

There is no WARNING in this case — the WARNING is for when recovery succeeded but the agent needs to know about state loss. A failed reconnect means the tool call itself failed; the agent should surface this to the user rather than attempting to proceed. The remote-mcp process does not exit after a failed reconnect — it stays alive so the user can investigate the network issue and retry.

## Why only one reconnect attempt

One retry catches the common case (brief VPN glitch, momentary network dropout) without hanging the tool call indefinitely for genuine outages. Two retries would double the worst-case wait time. Exponential backoff would make the first failure extremely slow to detect. One immediate retry, followed by an error if that fails, is the right balance between resilience and responsiveness.

## The reconnect flag lifecycle

`_reconnected` is set to `True` by `_do_reconnect()` after a successful reconnect. `check_and_clear_reconnect_flag()` in `call_tool()` reads the flag, clears it, and returns whether it was set — in one atomic operation. This ensures the WARNING appears exactly once: on the first tool call after the reconnect, not on every subsequent call. The "check and clear" atomicity is important; if the flag were checked and cleared separately, a concurrent tool call could see the flag twice or not at all.
