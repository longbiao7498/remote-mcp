# The Feedback Loop

> 中文版本：[feedback-loop.zh.md](./feedback-loop.zh.md)

Remote-mcp ships a `Feedback` tool. It is unusual: most tools exist to do something on the remote host, but Feedback exists for the agent to talk to the maintainer. This document explains why this tool exists, what it captures, and how it connects to the development cycle.

## The problem it solves

The developer of a tool like remote-mcp faces a fundamental visibility problem. The tool's users are largely AI agents, not humans. When an agent encounters a bug — a schema mismatch, a garbled output, an unexpected timeout — it adapts and continues. It might retry with different parameters, switch to a different tool, or simply report a vague failure to the user. The maintainer never hears about it.

When an agent realizes "this workflow would be much simpler if this tool had a context parameter", the thought has nowhere to go. The agent finishes the task and the observation evaporates.

Traditional bug reports require human intervention at the moment of failure. If the user notices something wrong and bothers to file an issue, the maintainer gets feedback. If they don't, the maintainer doesn't. For a tool that operates mostly at the agent layer, below the user's awareness, this feedback rate is close to zero.

The Feedback tool is a low-friction escape valve: the agent can record what it observed, in the moment, without interrupting its task, and the maintainer can review those observations later.

## What it captures

Feedback records two categories:

**`bug`**: The tool behaved in a way that was wrong relative to expectations. The schema was inconsistent with Claude Code's native tools. An error message was worded differently than the native equivalent. Output was truncated unexpectedly. A timeout fired on a command that should have succeeded. These are things the maintainer needs to know to fix.

**`enhancement`**: The agent encountered a workflow that required more round-trips than necessary, or wished a tool had a parameter it doesn't have, or realized a new tool would eliminate a pattern of two or three existing tool calls. These are things the maintainer needs to know to improve.

Each entry records: timestamp, host name, session PID, category, a one-line summary, and optional details. The host name and session PID allow the maintainer to correlate feedback entries with server logs if something needs deeper investigation.

See the [Feedback tool reference](../reference/tools/feedback.md) for exact parameter documentation.

## Why it's local-only, with no telemetry

The `details` field can contain code snippets. An agent explaining a bug with Glob might include the actual file paths and pattern it used. An agent suggesting a MultiWrite enhancement might include sample code from the project it's working on. That code belongs to the user's project, and it should not leave the user's machine without explicit consent.

The Feedback tool writes to a local JSONL file (`~/.local/share/remote-mcp/feedback.jsonl` by default) and does nothing else. No network requests, no analytics endpoints, no background sync. The user owns the file entirely. If they want to share feedback with the maintainer, they can send the file or paste relevant entries — that decision is theirs.

This is not a limitation to be worked around in a future version. It is a deliberate privacy stance.

## How the dev loop works

The intended cycle is:

1. The agent uses remote-mcp for real work on real projects.
2. When it notices a bug or has an enhancement idea, it calls `Feedback` and continues working.
3. Periodically, the maintainer reads `~/.local/share/remote-mcp/feedback.jsonl` — after a session, at the end of the week, or when triaging issues.
4. The maintainer deduplicates entries, identifies patterns, and prioritizes fixes or new features based on what the agent actually encountered in practice.
5. Changes ship in the next release, and the cycle repeats.

This is fundamentally different from a user filing a GitHub issue, because the observations happen at agent-time (when the agent is in the middle of the workflow and the context is richest) rather than at user-time (hours later, when the user vaguely remembers something was off). The agent captures the exact tool call, the exact output, and the exact expectation — detail that is almost always lost by the time a human files a bug report.

## What it is not for

Feedback is not a general-purpose note-taking tool. It is not for logging observations about the user's codebase, the remote system's health, or anything unrelated to the remote-mcp tools themselves. The tool description in the MCP schema is explicit about this: "Record a bug or enhancement idea about the remote-mcp tools themselves (NOT about the user's code or remote system)."

An agent that files a Feedback entry for a disk-full error on the remote host, or a syntax error in the user's Python code, is misusing the tool. These belong in the user's own tracking system, not in the remote-mcp feedback file.

## Why it's a dedicated tool rather than using Write

Three reasons: schema consistency, atomicity, and guidance.

**Schema consistency.** A Feedback entry has a defined structure: timestamp, host, category, summary, details, session_pid. If the agent writes a file directly, it must remember this schema on every call. The Feedback tool enforces it and populates the automatic fields (timestamp, host, PID) correctly without relying on the agent's memory.

**Atomicity.** Multiple remote-mcp processes (one per host) share the same feedback file. If two agents on two hosts simultaneously call Feedback, a raw file write could interleave their JSON. POSIX guarantees that `write()` calls under `PIPE_BUF` bytes (typically 4 KB) are atomic for regular files — and a single Feedback entry is well under that limit. The tool relies on this guarantee; a shell `echo >> file` approach would not.

**Guidance.** A dedicated tool with a well-written description, visible in the tool list, reminds the agent that this channel exists. A Write-to-file approach would require the agent to remember the file path, the schema, and the purpose — all from context alone. The Feedback tool is self-documenting in the way that Write is not.
