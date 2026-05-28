# Configured cwd and path resolution

> 中文版本：[cwd-and-path-resolution.zh.md](./cwd-and-path-resolution.zh.md)

> See also: [the v0.2.0 spec §6](../../superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md), authoritative.

In v0.1.x, every tool required absolute paths. `Read("config.yaml")` failed with `File not found`. The agent had to know the remote layout and prepend the path: `Read("/opt/myapp/config.yaml")`.

In v0.2.0, you configure a `cwd` per host (`--cwd /opt/myapp`), and relative paths resolve against it. `Read("config.yaml")` now reads `/opt/myapp/config.yaml`. This matches how Claude Code native works against your local project directory.

## Why "configured at registration", not "agent-controlled"?

We considered letting agents set or change cwd via a tool call (like a stateful `cd`). Rejected for two reasons:
1. Non-persistent Bash means agent `cd` already doesn't persist — adding agent-controlled cwd would be a parallel state machine, confusing.
2. CC native cwd is fixed at session start (the directory `claude` was launched in). Mirroring this keeps agent behavior predictable across CC native vs remote-mcp.

## Why suffix `[host=X cwd=Y]`, not prefix?

The suffix appears in every tool output (success, error, reconnect-warning). It's deliberately:
- **Suffix** so Read's `     1\t...` line numbering isn't mistakenly seen as the prefix
- **Configured cwd, not runtime pwd** so the agent always sees the stable "I'm in X" mental model — even if the agent's `command` did `cd /tmp`, the next call starts at the configured cwd, and the suffix reflects that

This is a proactive reminder, not a reactive correction. The agent should never form the wrong mental model in the first place.

## Why `~` in tool args is rejected

Tilde expansion depends on knowing the remote user's `$HOME`, which the agent doesn't know (and shouldn't assume). The MCP server expands `~` in the `cwd` config field once at connect time, but tool arguments stay literal — pass absolute or relative-to-cwd. If you really need `$HOME` in a tool arg, use the value RemoteInfo reports.

## Two-layer `~` policy in summary

- **cwd config** (`--cwd ~/projects/myapp` or `cwd: ~/projects/myapp`): expanded at connect time
- **Tool args** (`Read("~/foo.txt")`): error — pass absolute path or relative-to-cwd
