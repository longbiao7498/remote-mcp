# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

**Pre-implementation.** The only file currently present is `软件设计文档.md` — a Chinese-language design spec marked `状态: 待实施` ("status: pending implementation"). There is no code, no `pyproject.toml`, no tests, and no git history yet. New sessions are typically here to *implement* the design, not modify existing code. Read the design doc end-to-end before proposing changes to architecture — many decisions (sentinel protocol, reconnect warnings, SFTP-vs-exec split) have explicit rationales.

## What's being built

`remote-mcp` is a **local** Python MCP server that proxies Claude Code's six filesystem/shell tools (Read, Write, Edit, Bash, Glob, Grep) to a remote Linux host over SSH. Claude Code sees the same tool names and schemas as its built-ins; everything executes remotely. Hard constraints: remote host has SSH only (no agent install), transport is stdio MCP, SSH library is paramiko.

```
Claude Code  ──stdio MCP──▶  remote-mcp (local)  ──SSH/SFTP──▶  remote host
```

One MCP-server process per remote host, selected with `--host <name>` from `~/.config/remote-mcp/config.yaml`. Register each host as a separate entry via `claude mcp add`.

## Architecture (load-bearing pieces)

The design's correctness hinges on three subsystems. Get these wrong and nothing else matters.

### 1. Persistent bash session + Sentinel protocol (`bash_session.py`)

Bash is kept alive for the lifetime of the SSH connection so `cd`, `export`, and shell state persist across tool calls. Because stdout is a continuous stream with no "command done" signal, each `execute()` appends `echo "RMCP_SENTINEL_<uuid>_EXIT_$?"` and reads stdout line-by-line until the sentinel appears. A **background reader thread** is mandatory: paramiko channel buffers are small, and if the local side stops consuming, the remote bash will block on write and deadlock.

Init sequence after spawning `bash --norc --noprofile` is non-negotiable for the sentinel to parse cleanly: `set +m` (no job-control messages), `set +o histexpand` (no `!` expansion), `export PS1=''` (no prompt mixed into output), `export TERM=dumb`, `exec 2>&1` (stderr merged into stdout). Timeout sends `\x03` (Ctrl-C); the bash process survives for the next call.

### 2. SSH connection + SFTP + ProxyJump (`connection.py`)

One `SSHConnection` per remote host, holding: a paramiko `Transport`, a lazy SFTP client (reused), and a lazy `BashSession` (singleton for the connection's life). Two execution paths:
- `exec(cmd)` — stateless, one-shot channel. Used by Glob and Grep.
- `get_bash_session().execute(cmd)` — stateful persistent shell. Used by Bash.

File ops (Read/Write/Edit) use SFTP exclusively — binary-safe, no shell escaping. `transport.set_keepalive(interval)` must be enabled after `connect()` to survive VPN/firewall idle timeouts (default 30 s). ProxyJump is implemented by `open_channel("direct-tcpip", ...)` on the jump client and passing the resulting channel as `sock=` to the target client's `connect()`.

### 3. Reconnect detection with explicit agent warning

On SSH drop, auto-reconnect once. The bash session is rebuilt **and shell state (cwd, env vars) is gone**. Silent recovery is forbidden — the agent would keep using stale relative paths. `SSHConnection._reconnected` is set `True` after a successful reconnect; `call_tool()` in `server.py` checks-and-clears this flag and prefixes the tool result with a `[WARNING]` explaining: (a) connection was rebuilt, (b) cwd is back to `$HOME` and env is empty, (c) use absolute paths and re-run setup. All three points are required — vague "connection restored" messages are not acceptable. If reconnect itself fails, return `Error: SSH connection lost and reconnect failed` instead of a warning.

## Tool implementation conventions

- All tools return strings. **Failures return a string starting with `Error: ...`**, never raise. Claude Code adapts based on the error text.
- Tool names, parameter names, and output formats must match Claude Code's built-ins exactly (e.g., Read returns `     <lineno>\t<content>` with 1-based line numbers). The schema is locked in §5 of the design doc.
- Write does `mkdir -p` on the parent via `conn.exec` before SFTP-writing the file.
- Edit does read-modify-write through SFTP, requires `old_string` to appear exactly once, returns specific errors for 0 matches vs. >1 matches (with the count).
- Glob shells out to remote `find … -name <basename> | sort`. The design notes this only matches on filename, not full path semantics of `**` — implementer must confirm this is acceptable during acceptance testing.
- Grep shells out to remote `grep -rn[i] [--include=…] -E <pattern> <path> | head -200`. Exit codes: 0=match, 1=no match (return `"No matches found"`), 2=error.

## Planned project layout

```
remote_mcp/
├── __main__.py        # argparse, then asyncio.run(main(...))
├── server.py          # MCP Server, list_tools/call_tool, reconnect-warning dispatch
├── connection.py      # SSHConnection, HostConfig, ExecResult, ProxyJump
├── bash_session.py    # BashSession + sentinel protocol + reader thread
└── tools/
    ├── read.py write.py edit.py bash.py glob.py grep.py
```

Config lives in `~/.config/remote-mcp/config.yaml` (overridable with `--config`). See §6.1 of the design doc for the schema (hosts, key_path, jump_host, keepalive_interval, default_host).

## Implementation order

The design specifies a strict bottom-up order with per-stage acceptance criteria (§8). Don't skip ahead — later stages assume earlier ones are verified:

1. `connection.py` — exec, SFTP, ProxyJump, keepalive, reconnect flag
2. `bash_session.py` — **highest-risk stage**; build a standalone test script before integrating (cwd persistence, env persistence, special-char round-trip, timeout-without-killing-session)
3. Read / Write / Edit
4. Glob / Grep
5. `server.py` + `__main__.py` — wire into MCP stdio, register, smoke-test from Claude Code
6. Packaging + README

## Commands (once implemented)

```bash
pip install -e .
python -m remote_mcp --host <name> [--config <path>] [--test]
claude mcp add --global remote-<name> -- python -m remote_mcp --host <name>
```

There is no test runner, lint config, or CI yet — add these as part of stage 6 if needed.

## Known limitations baked into the design

Don't "fix" these without checking with the user first — they're explicit scope decisions in §9:

- No interactive/TTY commands (`vim`, `top`, REPLs).
- Text/UTF-8 files only for Write/Edit; no binary support.
- Glob `**` semantics are filename-only, not full recursive-path matching.
- Edit is not atomic — single-agent serial use only, no concurrent-writer protection.
- Read transfers the whole file then slices locally. Acceptable up to ~100 MB; for larger files switch to remote `sed -n` slicing.
