# Explanation

> 中文版本：[`README.zh.md`](./README.zh.md)

Explanation **illuminates**. It gives context, discusses alternatives, surfaces the *why* behind the design. Read it when you want to understand the system rather than use it.

An explanation is *not* a tutorial (no doing) and not a reference (no exhaustive lists). It's a discussion.

## Available explanations

| Topic | Why read it |
|-------|-------------|
| [Architecture overview](./architecture.md) | Get the mental model — what processes, what protocols, what flows where |
| [Design decisions](./design-decisions.md) | Understand the key choices (paramiko, stdio MCP, persistent bash, sentinel protocol, ...) and the alternatives that were rejected |
| [Bandwidth and latency](./bandwidth-and-latency.md) | The constraint that shaped almost everything else — why we slice server-side, why we have MultiRead/MultiEdit, why Bash supports background |
| [Multi-host model](./multi-host-model.md) | Why each host gets its own server process, why there's no federation, what happens when the agent works with 2-3 hosts at once |
| [Reconnect and the WARNING protocol](./reconnect-and-warning.md) | Why we never silently recover from a connection drop, why the WARNING text is so specific, what state survives and what doesn't |
| [The Feedback loop](./feedback-loop.md) | Why we ship a `Feedback` tool, what it's for, how it relates to the development cycle |

## What goes in explanation (for contributors)

- Discuss, don't instruct. "We chose X because Y" not "Do X if you want Y".
- Connect concepts to each other ("The persistent bash session is what enables sentinel protocol to work, which in turn means ...").
- Include the alternatives that were considered and why they were rejected — the negative space is informative.
- Cross-link to reference for exact facts; don't duplicate them here.
- It's OK to express opinions and judgments. Explanation has a voice.
