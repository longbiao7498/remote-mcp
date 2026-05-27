# How-to guides

> 中文版本：[`README.zh.md`](./README.zh.md)

How-to guides are **recipes** for solving specific problems. You already know what you want to accomplish — these tell you the steps. They assume basic familiarity with remote-mcp (see [the tutorial](../tutorial/first-remote-session.md) if you don't have that yet).

A how-to is *not* a tutorial (no teaching, no journey) and not reference (no exhaustive enumeration — just the steps that solve the stated problem).

## Operating remote-mcp

| Guide | Use when... |
|-------|-------------|
| [Configure multiple remote hosts](./configure-multi-host.md) | You work with 2–3 servers in one Claude Code session |
| [Set up ProxyJump (bastion host)](./set-up-proxyjump.md) | The target host is only reachable through a jump box |
| [Tune for slow / lossy networks](./tune-for-slow-networks.md) | You're on a high-latency or limited-bandwidth link |
| [Run long-running background jobs](./run-long-background-jobs.md) | You need to start a build/test/install that takes minutes and not block the agent |
| [Recover after a connection drop](./recover-from-disconnect.md) | You see a `[WARNING] SSH connection to <host> was lost` message |
| [Debug: MCP tools not appearing in Claude Code](./debug-mcp-not-appearing.md) | After `claude mcp add` + restart, the tools don't show up |
| [Inspect the feedback log](./inspect-feedback-log.md) | Read what the agent has filed about remote-mcp itself |

## Extending remote-mcp

| Guide | Use when... |
|-------|-------------|
| [Add a new tool](./add-a-new-tool.md) | You want to expose a new capability to the agent |

## What goes in a how-to (for contributors)

- Stated problem → numbered steps → done. No preamble explaining why the problem exists.
- Don't teach concepts — link to `explanation/` if needed.
- Don't enumerate all options — pick the one path that solves the stated problem; cross-link reference for other options.
- One guide = one specific outcome. If you need to cover variations, split into multiple guides.
