# Design Decisions

> 中文版本：[design-decisions.zh.md](./design-decisions.zh.md)

This document explains the key choices made in remote-mcp, what alternatives were considered, and why we chose what we chose. The reasoning here is as important as the decisions themselves — if you're considering a modification, understanding the "why" will tell you whether you're breaking something load-bearing.

## SSH library: paramiko vs. alternatives

**Decision:** Use paramiko.

**Considered alternatives:**
- `asyncssh`: fully async, more modern API, but adds a non-trivial dependency and requires async-all-the-way-down discipline throughout the codebase.
- `subprocess` + system `ssh` binary: zero additional dependencies, but gives you almost no control — no programmatic keepalive, no ProxyJump channel API, no SFTP client, and the system `ssh` must be configured correctly in ways that are hard to verify from Python.
- Fabric / Invoke: convenience wrappers around paramiko or subprocess, not appropriate for a library that needs fine-grained channel control.

**Why paramiko:** The hard constraints dictated the choice. We need SFTP (binary-safe file transfer), keepalive control at the SSH protocol level, and ProxyJump implemented as a `direct-tcpip` channel — not as a shell pipeline. Paramiko provides all three with a stable API and no other dependencies. The async model of asyncssh was rejected because the MCP server's async layer (the `mcp` SDK) and the SSH layer interact at a single `call_tool` boundary; running synchronous paramiko calls in an async context is straightforward with `asyncio.to_thread`, while restructuring everything for asyncssh would add complexity without benefit.

## Transport: stdio MCP vs. HTTP MCP

**Decision:** stdio MCP.

**Considered alternatives:**
- HTTP MCP (SSE transport): would allow the MCP server to run as a persistent daemon reachable by multiple Claude Code sessions simultaneously.

**Why stdio:** The target configuration is one remote host per user session. stdio MCP is spawned and managed by Claude Code directly — no ports to open, no daemon to keep alive, no authentication between the client and the server. The process lifecycle is simply "Claude Code is running" equals "the process is running". HTTP MCP would add operational complexity (port conflicts, daemon lifecycle, security) for a multi-session use case that is explicitly out of scope. The design constraint that says "2-3 hosts, not a fleet" makes stdio the clearly correct answer.

## One process per host vs. a federated server

**Decision:** One OS process per remote host, registered separately via `claude mcp add`.

**Considered alternatives:**
- A single process managing all remote hosts, with tool names like `Read(host="prod", path="...")`.

**Why per-host:** Three reasons. First, isolation: if the SSH connection to one host misbehaves or crashes, it cannot affect operations on other hosts. The process boundary is free crash isolation. Second, simplicity: the codebase has no host-routing logic, no per-host state multiplexing, and no shared connection pool to reason about. Third, naming: Claude Code's MCP namespace (`mcp__remote-prod__Read`) already encodes the host in the tool name, which makes agent behavior much clearer — the agent knows at the tool-call level which host it's targeting. A federated design would require the agent to pass `host=` as a parameter to every call, creating a new source of errors and a more complex schema.

The cost is linear resource growth: N hosts means N processes, N SSH connections, N bash sessions. For 2-3 hosts this is negligible. See [Multi-host model](./multi-host-model.md) for what happens at larger scales.

## Persistent bash session vs. exec for everything

**Decision:** Keep one bash process alive for the Transport's lifetime; use it for all Bash tool calls.

**Considered alternatives:**
- Open a fresh exec channel for every Bash tool call. Simple, stateless, no deadlock risk.

**Why persistent:** Shell state persistence is not a nice-to-have; it is the core value proposition of the Bash tool. When an agent `cd`s into a project directory, it expects subsequent commands to run there. When it `export`s an environment variable (a Python virtualenv activation, a `CARGO_HOME`, a database URL), it expects that variable to be visible in subsequent commands. A stateless exec model would require the agent to reconstruct its working context on every single call — which is both fragile and bandwidth-wasteful.

The cost of persistence is significant: we need the sentinel protocol, the background reader thread, and careful initialization. These are real complexities. But they are necessary complexities, not accidental ones.

## Sentinel protocol vs. alternative command-boundary detection

**Decision:** Append `echo "RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)"` after every command; read stdout line-by-line until the sentinel appears.

**Considered alternatives:**
- **Pseudo-terminal (PTY) with prompt detection:** Allocate a PTY, set a known prompt string like `PS1=RMCP_DONE> `, detect the prompt as the command boundary. This is how interactive SSH tools like Fabric's interactive mode work.
- **Separate status channel:** Run the command in one exec channel, run a status check in a second channel after a delay.
- **Fixed delimiter injection:** Always write a known string to a separate file descriptor, detect on that fd.

**Why sentinel:** PTY allocation was rejected for a specific, important reason: PTYs introduce terminal emulation semantics that corrupt output. Control sequences, line wrapping, and ANSI escape codes intended for a terminal emulator appear in the raw output stream. More critically, a PTY runs the shell in interactive mode, which reintroduces job-control notifications and other interactive behaviors that we explicitly suppress with `set +m`. The sentinel approach runs bash in non-interactive mode, which has clean, predictable output.

The sentinel itself is robust against accidental collision: each call generates a fresh UUID, so user command output cannot contain the sentinel for the current call (it would have to predict the UUID). The sentinel also carries the exit code and current working directory in the same line, saving a follow-up query for either piece of information.

The background reader thread is a mandatory companion to the sentinel. If the local side stops consuming bytes from the channel, paramiko's receive buffer fills, the remote bash blocks on write, and the sentinel never arrives — deadlock. The reader thread drains the buffer continuously into a line queue, and `execute()` reads from the queue. This is not an optimization; it is a correctness requirement.

## PTY allocation: why we don't request one

**Decision:** No PTY. bash runs in non-interactive mode.

This is closely related to the sentinel discussion above, but worth stating clearly. PTY allocation is what causes Ctrl-C (`\x03`) to function as an interrupt signal in an SSH session. Without a PTY, sending `\x03` to stdin has no special effect in a non-interactive bash.

However, for the timeout path, we do send `\x03` — and it works, because `exec 2>&1` merges stderr into stdout (making the channel a single stream), and bash in non-interactive mode does respond to `\x03` with SIGINT behavior when reading from a pipe in certain conditions. The key insight is that we do not need full PTY semantics — we only need the interrupt character to reach the running subprocess. This works without a PTY, and without the terminal-emulation pollution that a PTY brings.

## setsid for background processes

**Decision:** Wrap background commands with `setsid nohup bash -c <cmd>`.

**Considered alternatives:**
- Plain `cmd &` (ampersand backgrounding)
- `nohup cmd &` without `setsid`

**Why setsid:** The Bash tool initializes with `set +m`, which disables job control. In a bash without job control, `cmd &` still creates a child process, but it remains in the BashSession's process group. If the agent uses `kill -- -<pid>` to kill the process tree (the correct way to kill all subprocesses), the negative PID means "kill the entire process group" — which would include the persistent bash session itself. That would be catastrophic.

`setsid` creates a new session, making the background process the leader of a new process group with PID = PGID. `kill -- -<pid>` then kills exactly the background process and its descendants, leaving the BashSession intact. `nohup` provides an additional layer of protection against SIGHUP signals, though `setsid` already detaches from the controlling terminal.

Plain `nohup cmd &` without `setsid` was rejected because it doesn't solve the process group problem — the process still shares the parent's process group.

## SFTP vs. shell commands for file operations

**Decision:** Use SFTP for all file reads, writes, and edits.

**Considered alternatives:**
- `cat file` via exec for reads, `echo content > file` or heredoc via exec for writes.

**Why SFTP:** Shell-based file I/O requires escaping. A file containing a single quote, a dollar sign, a backslash, or a null byte cannot be written via `echo` without careful quoting — and getting quoting right for arbitrary user-provided content in a shell command is a classic source of bugs. SFTP operates at the byte level with no shell involvement. The content of a Write call is transmitted as raw bytes and stored exactly as provided.

Additionally, SFTP reuses an already-open channel. An `exec("cat file")` call opens a new channel, sends the command, waits for the result, and closes the channel. The SFTP client sends a structured `open` + `read` + `close` over the persistent SFTP channel with lower per-operation overhead.

The one case where SFTP cannot help is the `sed` slicing in Read and MultiRead — SFTP's read operation doesn't support line-range queries, only byte-range queries. Reconstructing line boundaries from byte offsets would require either a full file transfer or a two-pass approach. Using exec with `sed -n` is cleaner and avoids transmitting data we don't need.

## Read: remote sed-slicing vs. SFTP full transfer

**Decision:** Read uses `sed -n '{offset},{end}p; {end+1}q'` via exec, not SFTP full-file transfer.

This was a v2 change from v1's approach. V1 transferred the entire file via SFTP and sliced in Python. For small files, this is fine. For a 100 MB log file where the agent wants lines 5000–5020, v1 transferred 100 MB; v2 transfers a few kilobytes. The `sed -n` approach is strictly better for all file sizes and adds negligible server-side CPU load.

See [Bandwidth and latency](./bandwidth-and-latency.md) for the quantified comparison.

## Tool fidelity strategy: matching Claude Code's native schemas

**Decision:** For the six tools that correspond to Claude Code native tools (Read, Write, Edit, Bash, Glob, Grep), the tool name, parameter names, and output format must match the native schema exactly.

**Why:** Claude Code's agent has been trained on the native tool schemas. It knows that Read returns `"     5\tsome line"` and that an Edit failure says `"Error: old_string not found in <path>"`. If remote-mcp returns different formats — even plausible-looking ones — the agent may misinterpret results, misroute recovery logic, or use the wrong tool. This is not theoretical: the design document explicitly calls out that error messages must be worded exactly right for the agent's recovery strategies to work.

The three new tools (MultiRead, FileStat, Feedback) have no native counterparts, so their schemas are designed for self-consistency and resistance to misuse rather than native compatibility.

## Write parent directory: SFTP mkdir vs. exec

**Decision:** Use SFTP's own `mkdir` recursively, not `conn.exec("mkdir -p ...")`.

V1 used exec to run `mkdir -p` before writing. This opened a new exec channel, paid the channel setup cost, and then opened the SFTP channel for the write itself. V2 implements `_sftp_mkdirs()` using SFTP's `mkdir` operation on the already-open SFTP channel — no exec channel needed, one fewer round-trip.

## Glob: find with pattern translation vs. remote glob

**Decision:** Use `find ... -name` or `find ... -wholename` with a translation layer that converts glob patterns to find expressions.

**Considered alternatives:**
- `bash -c 'ls **/*.py'` with globstar enabled
- `find ... -name '*' | grep -E <pattern>`

**Why find with translation:** `find` is universally available on Linux, produces sorted, controllable output, and supports both `-name` (filename-only matching) and `-wholename` (full-path matching). The `**` glob syntax translates cleanly to recursive `-name` matching. The translation layer (`_glob_to_find`) is explicit about what it supports and where it falls short — that transparency is better than a hidden behavioral mismatch from shell globbing.

The known limitation is that the translation is approximate for complex patterns. This is documented explicitly and is acceptable for the tool's stated purpose.

## Output caps everywhere

**Decision:** Cap Read results at 256 KB, Bash output at 100 KB, Glob results at 1000 entries. Append a truncation notice when the cap fires.

**Why:** An agent that runs `find /` or `grep "e" /var/log` without caps can flood the MCP transport with megabytes of data, making the Claude Code session effectively unusable. The caps are not about saving bandwidth per se — they're about preventing accidental denial-of-service on the conversation context. The truncation notice tells the agent the result was cut, so it can narrow its query rather than acting on incomplete data silently.

## Reconnect: auto-retry once, then warn

**Decision:** On SSH drop, attempt one reconnect automatically. If it succeeds, set a flag so the next tool call prepends a WARNING. If it fails, return an Error.

**Why only one retry:** Retrying indefinitely would mean tool calls silently hang for potentially minutes while the process struggles to reconnect. One retry is enough to handle brief network interruptions (VPN reconnecting, brief firewall timeout) without masking genuine outages. See [Reconnect and the WARNING protocol](./reconnect-and-warning.md) for the full discussion.

## Feedback: local file vs. network telemetry

**Decision:** Feedback writes to a local JSONL file. It never sends data anywhere.

This is a fundamental privacy stance. The agent may include code snippets in the `details` field. Those snippets belong to the user's project. A telemetry endpoint would mean the user's proprietary code leaving their machine without explicit consent. The local file model means the user owns the data entirely and can choose what, if anything, to share with the maintainer. See [The Feedback loop](./feedback-loop.md) for the fuller rationale.
