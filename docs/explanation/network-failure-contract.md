# Network failure contract

> See also: [the v0.2.2 spec](../superpowers/specs/2026-05-28-network-robustness-design.md), authoritative.

remote-mcp's job is to proxy file and shell operations over SSH. SSH connections can fail in many ways — graceful disconnect, silent packet loss during laptop suspend, complete network outage. Earlier versions handled some of these well and others not at all. v0.2.2 establishes a unified behavioral contract for tools under network failure.

## The three rules

1. **Bounded time return.** Every tool call must return within a finite time, even if the network is misbehaving. No call may hang indefinitely waiting for a remote response.

2. **Success and failure are distinguishable.** The existing `Error: ...` convention is sufficient — agents can already pattern-match on the `Error:` prefix. We do not introduce structured error codes; what matters is that an error response cannot be mistaken for a successful one and vice versa.

3. **No lying.** When a tool returns `Error: ...`, it must not claim a state opposite to the remote reality. If the remote task succeeded but the response was lost, we do NOT return `Error: ... failed`. If the remote state is unknown, we say so explicitly rather than guessing.

The contracts are enforced at the framework layer (`connection.py`, `server.py`) so individual tool code stays simple. New tools don't need to implement error-analysis logic — they just need to return either output or an `Error:` string.

## Why these rules — four concrete failures

**Edit / MultiEdit auto-retry false negative.** SFTP completes the write on remote, but the response is lost in transit. v0.2.1 auto-retry re-runs Edit, which now sees the already-modified file and returns `Error: old_string not found`. Agent thinks the Edit failed, may try again, breaking the correctly-modified file. v0.2.2: Edit / MultiEdit / Bash are not auto-retried. Agent decides.

**SFTP silent hang.** No I/O timeout on SFTP channels. Laptop suspend → SFTP waits minutes for a response that won't come. v0.2.2: `op_timeout_default` (60s by default) makes paramiko raise `socket.timeout` after that idle window.

**Background bash orphan.** `setsid nohup bash -c "..." &; echo $!` — the bash process actually starts, but the `echo $!` response is lost. Agent thinks launch failed; doesn't know there's an orphan. v0.2.2: PID is written to `/tmp/rmcp-bg-<uuid>.pid` before the echo. Even if the echo response is lost, agent can `cat /tmp/rmcp-bg-*.pid` to recover.

**Snapshot rebuild lying WARNING.** `_create_snapshot` failed silently (stderr only) but WARNING text claimed `Snapshot was rebuilt`. Agent assumed environment was intact; subsequent Bash calls failed mysteriously. v0.2.2: snapshot is captured once at MCP startup, stored in local memory, persisted to `~/.cache/remote-mcp/`. Reconnect doesn't re-run `bash -ic`; it stat-checks the remote file and re-uploads from the local cache if missing. WARNING text has three variants reflecting actual state.

## What this means for agents

Most failures still self-heal: idempotent reads (Read, Glob, Grep, FileStat, MultiRead, Write, Upload, Download) auto-retry on SSH failure exactly as before, picking up a transparent reconnect. The only agent-visible behavioral change is for Edit / MultiEdit / Bash: they may now return `Error: <SSHException>: ...` on network blips that previously would have been transparently retried. The trade-off is correctness — silent retry of read-modify-write or stateful commands creates worse problems than the visible error.

See `CLAUDE.md.fragment.md` for agent-level guidance on how to react to each of the new error / WARNING strings.
