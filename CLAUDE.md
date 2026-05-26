# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

**Pre-implementation.** Repo contains only design artifacts: `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` (v2, authoritative), the prior `软件设计文档.md` (v1, superseded), and this CLAUDE.md. No code, no `pyproject.toml`, no tests yet. New sessions are typically here to *implement* the design, not modify it. **Read the v2 spec end-to-end** before proposing changes to architecture — many decisions (sentinel protocol, reconnect warnings, SFTP-vs-exec split, the 9-tool surface, MultiRead/FileStat additions, background-bash via setsid) have explicit rationales and shouldn't be re-litigated without checking with the user.

## What's being built

`remote-mcp` is a **local** Python MCP server that exposes ten tools (Read, Write, Edit, MultiEdit, MultiRead, FileStat, Bash, Glob, Grep, Feedback) to Claude Code. Nine operate on a remote Linux host over SSH; the tenth (Feedback) writes to a local JSONL file for agent-driven dev-loop bookkeeping. The seven with Claude Code native counterparts (Read/Write/Edit/MultiEdit/Bash/Glob/Grep) match their schemas and output formats; MultiRead/FileStat are bandwidth-driven additions with no native equivalent; Feedback is a self-improvement channel — agent files bugs/feature ideas about remote-mcp itself, maintainer reads later to drive iteration. Hard constraints: remote host has SSH only (no agent install), transport is stdio MCP, SSH library is paramiko.

The authoritative design is `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` (v2). The Chinese-language `软件设计文档.md` at repo root is the prior v1 draft — kept for reference but **superseded by v2**.

```
Claude Code  ──stdio MCP──▶  remote-mcp (local)  ──SSH/SFTP──▶  remote host
```

One MCP-server process per remote host, selected with `--host <name>` from `~/.config/remote-mcp/config.yaml`. Register each host as a separate entry via `claude mcp add`.

## Architecture (load-bearing pieces)

The design's correctness hinges on three subsystems. Get these wrong and nothing else matters.

### 1. Persistent bash session + Sentinel protocol (`bash_session.py`)

Bash is kept alive for the lifetime of the SSH connection so `cd`, `export`, and shell state persist across tool calls. Because stdout is a continuous stream with no "command done" signal, each `execute()` appends `echo "RMCP_SENTINEL_<uuid>_EXIT_$?_CWD_$(pwd)"` (sentinel captures **both** exit_code and cwd) and reads stdout line-by-line until the sentinel appears. The captured cwd is cached on the session and used by the Bash tool to prefix results with `[host=X cwd=Y]` for multi-host clarity. A **background reader thread** is mandatory: paramiko channel buffers are small, and if the local side stops consuming, the remote bash will block on write and deadlock.

Init sequence after spawning `bash --norc --noprofile` is non-negotiable for the sentinel to parse cleanly: `set +m` (no job-control messages), `set +o histexpand` (no `!` expansion), `export PS1=''` (no prompt mixed into output), `export TERM=dumb`, `exec 2>&1` (stderr merged into stdout). Timeout sends `\x03` (Ctrl-C); the bash process survives for the next call.

### 2. SSH connection + SFTP + ProxyJump (`connection.py`)

One `SSHConnection` per remote host, holding: a paramiko `Transport` (with **`compress=True`** — default-on SSH compression for 3-10× text savings), a lazy SFTP client (reused for Write/Edit/MultiEdit/FileStat), and a lazy `BashSession` (singleton for the connection's life). Two execution paths:
- `exec(cmd)` — stateless, one-shot channel. Used by Read (sed-slicing), Glob, Grep, MultiRead.
- `get_bash_session().execute(cmd)` — stateful persistent shell. Used by Bash (foreground + background launch).

File metadata reads (FileStat) go through SFTP `stat`, NOT a Bash call. `transport.set_keepalive(interval)` must be enabled after `connect()` to survive VPN/firewall idle timeouts (default 30 s). ProxyJump is implemented by `open_channel("direct-tcpip", ...)` on the jump client and passing the resulting channel as `sock=` to the target client's `connect()`.

### 3. Reconnect detection with explicit agent warning

On SSH drop, auto-reconnect once. The bash session is rebuilt **and shell state (cwd, env vars) is gone**. Silent recovery is forbidden — the agent would keep using stale relative paths. `SSHConnection._reconnected` is set `True` after a successful reconnect; `call_tool()` in `server.py` checks-and-clears this flag and prefixes the tool result with a `[WARNING] SSH connection to <host_name> was lost ...` explaining: (a) which host reconnected, (b) cwd is back to `$HOME` and env is empty, (c) use absolute paths and re-run setup. All four elements are required (the host name is critical in multi-host scenarios — without it, agent can't tell which host needs recovery). If reconnect itself fails, return `Error: SSH connection to <host> lost and reconnect failed: <reason>` instead of a warning.

## Tool implementation conventions

- All tools return strings. **Failures return a string starting with `Error: ...`**, never raise. Claude Code adapts based on the error text.
- For the 7 tools with native counterparts, names/parameters/output formats must match Claude Code built-ins exactly (e.g., Read returns `     <lineno>\t<content>` with 1-based line numbers). Error wording must be word-for-word — see spec §6.
- Read does remote `sed -n` slicing, NOT SFTP-whole-file-then-slice. Only fall back to SFTP when no offset/limit and file size < 1 MB.
- Write uses SFTP-native recursive mkdir, NOT `conn.exec("mkdir -p")`. Saves a channel round-trip.
- Edit does read-modify-write through SFTP, requires `old_string` to appear exactly once, returns specific errors for 0 matches vs. >1 matches (with the count). For >1 edits on the same file, use MultiEdit.
- MultiEdit is atomic across its edits list — if any edit fails (0 matches or >1 matches without `replace_all`), no write occurs.
- MultiRead batches N file reads into one `conn.exec`; chunks separated by `===FILE: <path>===` markers.
- FileStat uses SFTP's native `stat`, NOT `Bash("stat ...")` — saves channel build, returns structured data.
- Bash with `run_in_background=true` wraps the user command in `setsid nohup bash -c '...' > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`. Returns PID + log path + 4 ready-to-paste command templates (status / read output / stop / force-stop). The `setsid` is **non-optional** — without it `kill -- -<pid>` would also kill the BashSession.
- Glob converts `**` patterns to `find -wholename` / `-path` to preserve path-segment semantics; not just `-name <basename>` (which was v1).
- Grep supports `-A/-B/-C` context lines, `head_limit`, `output_mode` (content/files_with_matches/count). Bandwidth win: agent can get matches + surrounding context in one call instead of grep-then-multiple-reads.
- Feedback appends a JSONL entry to `~/.local/share/remote-mcp/feedback.jsonl` (path overridable via top-level `feedback_path` in config). Single `write()` of a JSONL line is POSIX-atomic for typical sizes — multiple per-host processes can write the same file safely. Tool itself does not transmit anywhere; the file is the maintainer's data.

## Planned project layout

```
remote_mcp/
├── __main__.py        # argparse, then asyncio.run(main(...))
├── server.py          # MCP Server, list_tools/call_tool, reconnect-warning dispatch (incl. host name)
├── connection.py      # SSHConnection (compress=True default), HostConfig, ExecResult, ProxyJump
├── bash_session.py    # BashSession + sentinel protocol (captures exit_code AND cwd) + reader thread
└── tools/
    ├── read.py write.py edit.py multi_edit.py multi_read.py file_stat.py bash.py glob.py grep.py feedback.py
CLAUDE.md.fragment.md  # shipped at repo root; users copy to their remote project's CLAUDE.md
```

Config lives in `~/.config/remote-mcp/config.yaml` (overridable with `--config`). See spec §11 for schema (hosts, key_path, jump_host, keepalive_interval, compression, bash_timeout_default, glob_output_limit, read_size_cap, bash_output_cap, default_host).

## Implementation order

Strict bottom-up; per-stage acceptance criteria in spec §13. Don't skip ahead.

1. `connection.py` — exec, SFTP, ProxyJump, keepalive, **compression=True**, reconnect flag
2. `bash_session.py` — **highest-risk stage**; build a standalone test script before integrating. Sentinel format `RMCP_SENTINEL_<uuid>_EXIT_$?_CWD_$(pwd)` — capture exit_code AND cwd together
3. File tools: Read (sed-slicing) / Write (SFTP mkdir) / Edit / MultiEdit / **MultiRead** / **FileStat**
4. Search tools: Glob (`**` via `-wholename`) / Grep (with `-A/-B/-C`, `head_limit`, `output_mode`)
5. `server.py` + `__main__.py` + Bash tool (foreground AND **`run_in_background`**) + **Feedback** (local JSONL append)
6. Packaging + README + `CLAUDE.md.fragment.md`

## Commands (once implemented)

```bash
pip install -e .
python -m remote_mcp --host <name> [--config <path>] [--test]
claude mcp add --global remote-<name> -- python -m remote_mcp --host <name>
```

There is no test runner, lint config, or CI yet — add these as part of stage 6 if needed.

## Known limitations baked into the design

Don't "fix" these without checking with the user first — they're explicit scope decisions in spec §14:

- No interactive/TTY commands (`vim`, `top`, REPLs).
- Text/UTF-8 files only for Write/Edit/MultiEdit; no binary support.
- Edit/MultiEdit are not cross-process atomic — single-agent serial use only.
- Glob `**` semantics are *approximate*, not 100% equivalent to native — implementer should run the test cases in spec §13 stage 4 to catch divergences.
- Grep `multiline` parameter intentionally unsupported (POSIX grep limitation; agent should use `awk`/`perl -0` via Bash for multi-line patterns).
- Background bash logs in `/tmp/rmcp-bg-*.log` are not auto-cleaned on server exit (deliberate — leave for post-mortem; `/tmp` reboot cleans).
- Background bash PID reuse is a known low-probability hazard — agent should `kill -0 <pid>` before sending kill signals.
- Cross-host operations (e.g. copy file from prod to gpu) are NOT first-class — out of scope entirely. Use `Bash("scp prod:path gpu:path")` with user-arranged SSH trust.
- Performance not tuned for >3 simultaneous hosts (each runs its own Python process). Federation/plugin form is future work.
- Feedback file is not auto-rotated; maintainer archives manually. No upstream telemetry — purely local dev loop.
