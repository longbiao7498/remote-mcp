# Multi-Host Model

> 中文版本：[multi-host-model.zh.md](./multi-host-model.zh.md)

Remote-mcp is designed to support a common but non-trivial workflow: a single Claude Code session operating across two or three remote hosts simultaneously. This document explains the design choices behind that support, why the model is deliberately simple, and where it starts to strain.

## The core model: one process per host

Each remote host is represented by a separate remote-mcp OS process. You register hosts independently:

```bash
claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
claude mcp add --scope user remote-gpu  -- python -m remote_mcp --host gpu
```

Claude Code sees ten tools per host, namespaced by the registration name:

```
mcp__remote-prod__Read
mcp__remote-prod__Bash
mcp__remote-prod__Grep
...
mcp__remote-gpu__Read
mcp__remote-gpu__Bash
...
```

This is the simplest possible model. Each process is completely isolated from the others — separate memory, separate SSH connection, separate bash session. They cannot interfere with each other at any level below the user's filesystem (where both might read/write the same NFS mount, but that's the user's concern, not ours).

## Why not a federated design?

The obvious alternative would be a single remote-mcp process that manages all configured hosts, exposing tools like `Read(host="prod", path="...")`. This would save one process per host and allow shared connection pooling.

We rejected this for several reasons:

**Schema complexity.** A `host` parameter on every tool call is a new source of errors. The agent might forget it, or pass the wrong host name, or not realize that `host` is required. The per-host namespace makes host identity structural — it cannot be omitted.

**Blast radius.** A bug in the connection management code for one host could corrupt state for all hosts in a federated process. A crash in one host's process doesn't touch the others.

**Simplicity of implementation.** The federated model requires routing logic, per-host state management within one process, and careful handling of concurrent tool calls that target different hosts. The per-process model has none of that. Each process is a single-tenant server.

**The use case doesn't demand it.** The design explicitly targets 2-3 hosts, not a fleet. Two extra OS processes and two extra SSH connections are not a meaningful resource cost for a developer's machine. If you're managing ten hosts, you should probably be using a proper configuration management system, not a conversational AI agent.

## What [host=X cwd=Y] is for

Every Bash tool result is prefixed with a line like:

```
[host=prod cwd=/home/ubuntu/myproject]
```

This exists specifically for multi-host sessions. When an agent is switching between hosts — running a migration on `prod`, checking a model on `gpu`, querying a database on `db` — the tool results arrive in sequence in the conversation context. Without the host prefix, the agent cannot reliably tell which host's bash session is in which working directory. With the prefix, every result is self-describing.

The cwd is captured from the sentinel protocol: each command appends `echo "RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)"` to bash stdin, and the bash session parses the current working directory out of the sentinel line. This happens at the protocol level, not as an extra command, so there's no additional RTT cost.

## What the host name in WARNING messages is for

When an SSH connection drops and reconnects, the tool result is prefixed with:

```
[WARNING] SSH connection to prod was lost and has been re-established.
```

The host name in the warning serves the same purpose as the host prefix in Bash results: in a multi-host session, the agent needs to know which host lost its state, not just that some host did. A vague "connection was re-established" message would leave the agent uncertain about which bash session was reset and which workflows need to be restarted. See [Reconnect and the WARNING protocol](./reconnect-and-warning.md) for the full discussion.

## What the agent should know when working with multiple hosts

**Keep work host-local when possible.** The more an operation spans multiple hosts, the higher the coordination overhead. An agent that bounces between `prod` and `gpu` every few tool calls is paying two RTTs where one would do.

**Cross-host file transfer goes through Bash, not Read+Write.** An agent must not copy a file from `prod` to `gpu` by reading it via `mcp__remote-prod__Read` and writing it via `mcp__remote-gpu__Write`. This double-transfers the file: from `prod` to the local machine, and then from the local machine to `gpu`. The correct approach is `Bash("scp prod:/path/to/file /destination")` on the host that has SSH access to the other — which requires the user to have configured SSH keys between the hosts.

**State is host-local.** A `cd` on `prod`'s bash session has no effect on `gpu`'s bash session. An environment variable exported on one host does not appear on the other. This is obvious but worth stating explicitly: the agent cannot assume that setup done on one host carries over.

## Where the model strains

The per-host process model scales linearly. Each additional host adds:
- One OS process
- One SSH TCP connection
- One persistent bash channel
- One SFTP client

For 2-3 hosts this is comfortable. For 10 hosts on a laptop with 16 GB RAM, you're looking at 10 Python interpreter instances (each ~30-50 MB baseline), 10 SSH connections (small), and 10 bash processes on the remote side. That's roughly 300-500 MB of local memory and 10 SSH sessions on the remote, which is probably fine but getting uncomfortable.

Above 10 hosts, the right answer is a different architecture: a single connection-pool daemon, a shared SFTP session, or a proper remote execution framework. This is explicitly called out as future work. For now, if you're working with many hosts simultaneously, consider whether you actually need them all active at once or whether a serial workflow (register, work, deregister) is sufficient.

## The non-goal: cross-host primitives

There is no `Copy(from_host, to_host)` tool. There is no `MultiHostBash(hosts=[...], command=...)`. These were considered and explicitly deferred.

Cross-host operations are genuinely hard to get right — error handling, partial success, rollback, and atomicity all become dramatically more complex when multiple SSH connections are involved. The Bash + scp workaround handles the cases that actually arise in practice, at the cost of requiring the user to configure SSH trust between hosts. This is an acceptable trade-off for the 2-3 host use case.
