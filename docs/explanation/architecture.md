# Architecture Overview

> 中文版本：[architecture.zh.md](./architecture.zh.md)

This document builds the mental model you need to understand remote-mcp: what processes exist, what protocols connect them, what flows where, and why the layering is structured the way it is. Read it before diving into any individual module — the design makes much more sense once you see the whole topology.

## The fundamental premise

remote-mcp exists to solve a simple problem with a surprisingly rich solution space: Claude Code's built-in filesystem and shell tools operate on the local machine, but the files and processes you want to manipulate live on a remote Linux server reachable only over SSH.

The naive answer — "just SSH into the remote and run commands" — ignores that Claude Code isn't a shell; it's an agent that issues structured tool calls with typed parameters and reads typed responses. The challenge is to make the remote host's filesystem and shell feel, to Claude Code, indistinguishable from local resources.

## Process topology

```
┌──────────────────────────────────────────────────────────────┐
│                         Local machine                        │
│                                                              │
│  ┌──────────────┐    stdio MCP     ┌──────────────────────┐  │
│  │  Claude Code │ ◄──────────────► │     remote-mcp       │  │
│  │              │   (JSON-RPC 2.0) │  (one OS process     │  │
│  └──────────────┘                  │   per remote host)   │  │
│                                    └──────────┬───────────┘  │
└───────────────────────────────────────────────│──────────────┘
                                                │
                              SSH (compress=on, keepalive=30s)
                              one persistent TCP connection
                                                │
                    ┌───────────────────────────▼──────────────┐
                    │              Remote Linux host            │
                    │                                          │
                    │   Native filesystem (via SFTP)           │
                    │   Per-call exec channels (incl. Bash)    │
                    └──────────────────────────────────────────┘
```

Two boundaries matter here: the stdio MCP boundary between Claude Code and remote-mcp, and the SSH boundary between remote-mcp and the remote host. Everything interesting happens in the remote-mcp process that sits between them.

## The per-host process model

Each remote host gets its own remote-mcp OS process. This is not a daemon that manages multiple connections — it is a single-purpose relay, one process per host. Claude Code spawns this process when it starts, and the process lives for the entire duration of the Claude Code session. When Claude Code closes, the stdio pipe gets an EOF, the process's `try/finally` fires, and the SSH connection is torn down cleanly.

The registration looks like this:

```bash
claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
claude mcp add --scope user remote-gpu  -- python -m remote_mcp --host gpu
```

Two hosts, two processes, two SSH connections. They share nothing at runtime. Claude Code sees tools named `mcp__remote-prod__Read`, `mcp__remote-gpu__Bash`, and so on — the MCP namespace prefix makes the host identity visible in every tool call.

This is a deliberately simple model. See [Multi-host model](./multi-host-model.md) for a discussion of its limits and why a federated alternative was rejected.

## The SSH Transport and its channels

Inside the remote-mcp process, a single paramiko `Transport` sits at the core. A Transport is a persistent TCP connection that has been upgraded to the SSH session state — host key verification done, encryption negotiated, authentication complete. All subsequent communication flows through this one TCP connection, multiplexed across multiple SSH channels.

The channel types and their lifecycles:

```
┌─────────────────────────────────────────────────────────────────┐
│  remote-mcp OS process  (lives for the entire Claude Code session)
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  paramiko Transport  (one persistent TCP + SSH session)  │   │
│  │                                                          │   │
│  │  ┌─────────────────┐  ┌──────────────────────────────┐  │   │
│  │  │   SFTP client   │  │ exec ×N  (short-lived,        │  │   │
│  │  │  (lazy-init,    │  │ per call — Bash, Glob, Grep,  │  │   │
│  │  │  reused for all │  │ Read, MultiRead, and all       │  │   │
│  │  │  file ops)      │  │ other command-running tools)  │  │   │
│  │  └─────────────────┘  └──────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  disconnect / reconnect → entire Transport subtree is rebuilt   │
└─────────────────────────────────────────────────────────────────┘
```

### Per-call exec channels for Bash (v0.2.0+)

Since v0.2.0, the Bash tool no longer keeps a persistent bash process alive. Each Bash tool call opens a fresh exec channel, runs the command, and closes the channel when done — the same model used by Glob, Grep, Read (sed path), and MultiRead. There is no shared shell state between calls.

The convenience of "shell environment is loaded once" is preserved via a **snapshot mechanism**: at connect time, `bash -ic 'declare -p; declare -fp; alias'` captures the bashrc-loaded environment (PATH, aliases, conda init, etc.) and writes it to a snapshot file on the remote host. Each Bash call `source`s the snapshot before running the user's command, so PATH and other startup environment values are available — without paying the bashrc startup cost on every call.

The configured `cwd` (set at registration time via `--cwd`) is appended to the snapshot as `cd <cwd>`, so each Bash call begins in the right working directory. See [Configured cwd and path resolution](./cwd-and-path-resolution.md) for how this fits into the broader path-handling model.

Why this change was made is documented in depth in [Why non-persistent Bash](./why-non-persistent-bash.md).

### The SFTP client

SFTP is initialized lazily on the first file operation and reused thereafter. It is used exclusively for file read, write, and edit operations. Choosing SFTP over shell commands for file I/O was deliberate: SFTP is binary-safe, requires no shell escaping, and reuses an already-open channel. A file containing single quotes, dollar signs, or newlines is transferred correctly with zero special handling.

The Write tool uses SFTP's own mkdir capability to create parent directories, avoiding an extra exec channel round-trip.

### Ephemeral exec channels

Glob and Grep use `SSHConnection.exec()`, which opens a fresh channel, runs the command, reads the result, and closes the channel. These tools are inherently stateless — there is no concept of "current directory" for a grep invocation. The exec model is the right fit: simple, isolated, no shared state to corrupt.

The Read tool's remote `sed` slicing also uses exec channels, as do the multi-file scripts constructed by MultiRead.

## Two execution paths

Every tool call lands on one of two paths:

**Exec path** (Bash, Glob, Grep, Read, MultiRead, Write's mkdir): `SSHConnection.exec(command)` opens a channel, runs the command, returns stdout + stderr + exit code, closes the channel. No shared state, no persistence, no ordering constraints. As of v0.2.0, Bash joins this path — it wraps the user command with a snapshot `source` before running it via exec, rather than using a persistent bash channel.

**SFTP path** (Read full-file, Write, Edit, MultiEdit, MultiRead data, FileStat): operations go through the persistent SFTP channel without opening new exec channels. Binary-safe, no shell escaping required.

This split is load-bearing. SFTP handles file content reliably regardless of what characters are in the file. Exec handles command execution cleanly without the complexity of a persistent bash session.

## File operations: SFTP only

Read (full-file path, not the sed-slicing path), Write, Edit, MultiEdit, MultiRead, and FileStat all use SFTP for the actual file transfer. SFTP operations run over the persistent SFTP channel without opening new exec channels. The only reason exec channels appear in file-related tools is for the `sed` slicing in Read and MultiRead — the actual data comes back through the exec result, not through SFTP.

FileStat deserves a special mention: it uses SFTP `stat()` calls, which return structured metadata (size, mtime, mode, type) in a few bytes. This is the correct tool for "does this file exist and how big is it?" — not Read, which would transfer the entire file.

## Keepalive and connection stability

`transport.set_keepalive(30)` sends a heartbeat every 30 seconds at the SSH protocol level. This matters because the remote-mcp process can be idle for minutes between tool calls, and many VPNs and firewalls silently drop TCP connections that appear idle. The keepalive prevents this without any visible effect on tool calls.

When the connection does drop, the reconnect behavior involves rebuilding the entire Transport subtree — a new TCP connection, new authentication, new bash process, new SFTP client. What this means for the agent is explained in [Reconnect and the WARNING protocol](./reconnect-and-warning.md).

## ProxyJump

For hosts reachable only through a jump server, remote-mcp implements ProxyJump using paramiko's channel API: it opens a `direct-tcpip` channel on the jump host's Transport (which provides a TCP-like stream to the target), then passes that channel as the `sock=` argument to the target host's `connect()`. The result is an SSH connection that looks, from the target's perspective, like a normal incoming connection, but whose bytes physically travel through the jump host.

The jump host is configured in `config.yaml` as `jump_host: <name>`, referencing another entry in the same hosts map.

## SSH compression

All SSH traffic is sent with `compress=True`. For the text-heavy workloads that dominate remote development (source files, log output, command results), this typically achieves 3–10× compression ratios. The CPU cost is negligible on modern hardware. This is a transparent optimization: nothing in the tool layer needs to be aware of it.

See [Bandwidth and latency](./bandwidth-and-latency.md) for the full picture of how the design handles constrained network conditions.

## Where each tool fits

| Tool | Channel type | Notes |
|------|-------------|-------|
| Read (sed path) | exec | stateless |
| Write | SFTP (mkdir via exec) | stateless |
| Edit | SFTP | stateless |
| MultiEdit | SFTP | stateless |
| MultiRead | exec (one command) | stateless |
| FileStat | SFTP stat | stateless |
| Bash | exec (snapshot-wrapped) | stateless per-call; snapshot provides env |
| Glob | exec | stateless |
| Grep | exec | stateless |
| Feedback | local file write | local only |

Feedback is the odd one out: it writes to a local file and never touches the SSH connection. It captures agent observations about the tools themselves, not about the remote system. See [The Feedback loop](./feedback-loop.md).
