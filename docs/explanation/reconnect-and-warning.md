# Reconnect and the WARNING Protocol

> 中文版本：[reconnect-and-warning.zh.md](./reconnect-and-warning.zh.md)

An SSH connection to a remote host can drop for many reasons: VPN reconnection, firewall idle timeout, network blip, server restart. Remote-mcp handles this automatically — but the recovery is not silent. This document explains why automatic recovery requires an explicit warning, what the warning says and why each part matters, and what state the agent can and cannot rely on after a reconnect.

## Why silent recovery is forbidden

The tempting behavior is to reconnect quietly and let the agent continue as if nothing happened. Even under the v0.2.0 non-persistent Bash model — where there is no accumulated shell state to lose — silent recovery is still wrong for one important reason: the agent deserves to know that the underlying transport had a disruption.

In the v0.1.x persistent bash model, the consequences of a silent reconnect were severe: cwd and all environment variables were gone, and the agent would silently operate on wrong assumptions. In v0.2.0, the consequences are milder (the snapshot is rebuilt, and the configured cwd is always the starting point), but silent recovery still violates the principle that the agent should have an accurate model of what happened. If the reconnect took several seconds, tool calls issued during that window may have failed. The agent should know.

Silent recovery trades a small immediate clarity (the warning) for potential confusion about which tool calls succeeded, which host had the issue, and whether the current snapshot reflects the latest environment. This is not a trade worth making.

## The WARNING structure

The warning text is a contract. When `SSHConnection._reconnected` is set after a successful reconnect, the next `call_tool()` invocation checks the flag, clears it, and prepends this warning to the tool result:

```
[WARNING] SSH connection to <host_name> was lost and has been re-established.
Snapshot was rebuilt; if your bashrc has changed since the connection started,
the new state takes effect from this point.
```

Each part serves a specific purpose:

**"SSH connection to \<host_name\> was lost and has been re-established."** — This tells the agent what happened. In a multi-host session, the agent needs to know which host was affected. A vague "connection restored" message would leave it uncertain about whether `prod` or `gpu` was affected. The host name makes the scope of the disruption unambiguous.

**"Snapshot was rebuilt; if your bashrc has changed since the connection started, the new state takes effect from this point."** — This tells the agent the one meaningful consequence of the reconnect under the v0.2.0 non-persistent model. Because each Bash call already starts from a fresh shell sourcing the snapshot, there is no accumulated shell state to lose. The only thing the agent needs to know is that the snapshot was rebuilt from the current bashrc — if bashrc changed during the outage, new Bash calls will reflect those changes. The agent can continue issuing commands exactly as before; no recovery actions are required.

This is a deliberate simplification from the v0.1.x warning, which told agents to "use absolute paths and re-run setup commands". That advice was correct under persistent bash (where cwd and env vars were lost), but is no longer necessary: the configured cwd is fixed in `config.yaml`, and the snapshot mechanism means environment setup is automatic on every call.

## What survives a reconnect and what doesn't

**Survives:**
- The `SSHConnection` object and its configuration (hostname, user, key path, keepalive settings, configured cwd)
- The host registration in Claude Code's tool namespace
- The configuration in `config.yaml`
- Any files written to the remote filesystem (writes went through SFTP to disk)
- The effective cwd: because cwd is configured at registration time (not tracked as bash session state), each Bash call still starts at the configured cwd after reconnect

**Does not survive:**
- The bash snapshot file on the remote `/tmp`: it is rebuilt after reconnect. Any bashrc changes made between the original connect and the reconnect will be reflected in the new snapshot.
- The SFTP client: it is re-initialized lazily after reconnect, which is transparent
- Any in-flight tool calls at the moment of the drop: these return an error (the connection was lost while the operation was in progress)
- Background processes started with `run_in_background=true`: these are descendants of `setsid` and live in their own session — if the host itself is still running, `setsid`-ed processes survive, but the agent should check carefully (with `kill -0 <pid>`) before assuming they are still running

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
