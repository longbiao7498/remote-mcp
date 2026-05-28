# CLAUDE.md

> 中文版本：[CLAUDE.zh.md](./CLAUDE.zh.md)

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For user-facing documentation organized along the Diátaxis framework (tutorial / how-to / reference / explanation), see [`docs/`](./docs/). This file is specifically for Claude Code's perspective — it surfaces the load-bearing decisions and conventions that an agent modifying this codebase needs to know upfront.

## Repository status

**v0.2.0 implemented.** Stages A–C (non-persistent Bash, configurable cwd, unified output suffix) are complete. The authoritative design is `docs/superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md` (v0.2.0 spec, incremental over v2). The v2 spec `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` remains authoritative for everything not overridden by the v0.2.0 spec. New sessions working on this repo: **read both specs end-to-end** before proposing architecture changes — many decisions (snapshot mechanism, cwd policy, `~` two-layer semantics, unified suffix, SFTP-vs-exec split, the tool surface, background-bash via setsid) have explicit rationales and shouldn't be re-litigated without checking with the user.

## What's being built

`remote-mcp` is a **local** Python MCP server that exposes ten tools (Read, Write, Edit, MultiEdit, MultiRead, FileStat, Bash, Glob, Grep, Feedback) to Claude Code. Nine operate on a remote Linux host over SSH; the tenth (Feedback) writes to a local JSONL file for agent-driven dev-loop bookkeeping. The seven with Claude Code native counterparts (Read/Write/Edit/MultiEdit/Bash/Glob/Grep) match their schemas and output formats; MultiRead/FileStat are bandwidth-driven additions with no native equivalent; Feedback is a self-improvement channel — agent files bugs/feature ideas about remote-mcp itself, maintainer reads later to drive iteration. Hard constraints: remote host has SSH only (no agent install), transport is stdio MCP, SSH library is paramiko.

The authoritative designs are `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` (v2, base) and `docs/superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md` (v0.2.0 increment). The Chinese-language `软件设计文档.md` at repo root is the prior v1 draft — kept for reference but **superseded by v2**.

```
Claude Code  ──stdio MCP──▶  remote-mcp (local)  ──SSH/SFTP──▶  remote host
```

One MCP-server process per remote host, selected with `--host <name>` from `~/.config/remote-mcp/config.yaml`. Register each host as a separate entry via `claude mcp add`.

## Architecture (load-bearing pieces)

The design's correctness hinges on three subsystems. Get these wrong and nothing else matters.

### 1. Non-persistent Bash + Snapshot replay (`tools/bash.py` + `connection.py::_create_snapshot`)

Each Bash invocation is a fresh `bash --noprofile --norc -c "source /tmp/rmcp-snapshot-<host>-<pid>.sh 2>/dev/null || true; <cmd>" </dev/null`. The snapshot is created once per SSH connection by `bash -ic 'declare -p; declare -fp; alias'` and gets `cd <configured-cwd> || exit 1` appended so every Bash starts at the configured cwd. **Behavior matches Claude Code native Bash**: shell state (cwd, env, source'd venvs) does NOT persist across calls. Agents wanting to chain state must do it inline (`cd dir && cmd`, `VAR=v cmd`, `venv/bin/python script.py`).

`</dev/null` on stdin is non-negotiable — it makes `srun`, `cat` (no args), and other stdin-reading commands return immediately instead of hanging. Timeout uses `channel.close()` (SIGHUP via SSH session close); no PTY is allocated.

### 2. Configurable cwd + path resolution (`paths.py` + `connection.py::_resolve_and_validate_cwd`)

`--cwd /opt/app` (CLI) or `hosts.<name>.cwd` (YAML) anchors all relative paths. Format must be `/...`, `~`, or `~/...`. `~` is expanded once at connect time via `bash -c 'echo $HOME'` and written back to `self.config.cwd` (so RemoteInfo / suffix / snapshot all show the same absolute path). SFTP `stat` validates existence at startup (fail-fast — bad cwd → MCP server refuses to start). Default (no cwd configured) acts as `cwd: ~`.

All non-Bash tools call `paths.resolve_path(path, conn.config.cwd)`:
- Absolute → as-is
- Relative → `posixpath.normpath(posixpath.join(cwd, path))`
- Empty → `ValueError("empty path")`
- `~`-prefixed → `ValueError("path starts with '~'...")`

Bash's cwd is set by the `cd` appended to the snapshot, not via `resolve_path` (the agent's `command` string may reference paths in shell expressions; we don't parse it).

### 3. SSH connection + SFTP + ProxyJump (`connection.py`)

**Process model and connection lifecycle**: each registered `mcp__remote-<host>__` is a **long-lived OS process**, not a per-call spawn. It stays alive for the entire Claude Code session. `main()` builds one `SSHConnection` at startup, all tool calls share it, `conn.close()` runs in `finally` when stdio closes. One `SSHConnection` per process, holding: a paramiko `Transport` (with **`compress=True`** — default-on SSH compression for 3-10× text savings) that supports a lazy SFTP channel + per-call ephemeral exec channels. All tool calls (including Bash) use `exec(cmd)` — stateless, one-shot channels.

File metadata reads (FileStat) go through SFTP `stat`, NOT a Bash call. `transport.set_keepalive(interval)` must be enabled after `connect()` to survive VPN/firewall idle timeouts (default 30 s). ProxyJump is implemented by `open_channel("direct-tcpip", ...)` on the jump client and passing the resulting channel as `sock=` to the target client's `connect()`.

### 4. Unified output suffix (`server.py::call_tool`)

`server.py::call_tool()` wraps every tool result with `\n\n[host=X cwd=Y]`. **Tools must NOT prepend their own host/cwd prefix** (the old `tools/bash.py:59` style is gone). Errors get the suffix too — agents see `Error: File not found: foo.txt\n\n[host=prod cwd=/opt/app]` and can infer relative-path resolution failures at a glance.

### 5. Reconnect detection with explicit agent warning

On SSH drop, auto-reconnect once. The snapshot is rebuilt on reconnect. Silent recovery is forbidden — the agent needs to know the connection was interrupted. `SSHConnection._reconnected` is set `True` after a successful reconnect; `call_tool()` in `server.py` checks-and-clears this flag and prepends the tool result with `[WARNING] SSH connection to <host_name> was lost and has been re-established. Snapshot was rebuilt; if your bashrc has changed since the connection started, the new state takes effect from this point.` The host name is critical in multi-host scenarios. If reconnect itself fails, return `Error: SSH connection to <host> lost and reconnect failed: <reason>` instead of a warning.

## Tool implementation conventions

- All tools return strings. **Failures return a string starting with `Error: ...`**, never raise. Claude Code adapts based on the error text.
- For the 7 tools with native counterparts, names/parameters/output formats must match Claude Code built-ins exactly (e.g., Read returns `     <lineno>\t<content>` with 1-based line numbers). Error wording must be word-for-word — see spec §6.
- Read does remote `sed -n` slicing, NOT SFTP-whole-file-then-slice. Only fall back to SFTP when no offset/limit and file size < 1 MB.
- Write uses SFTP-native recursive mkdir (see `_sftp_mkdirs` in `tools/write.py`), NOT `conn.exec("mkdir -p")`. Saves a channel round-trip.
- Edit does read-modify-write through SFTP, requires `old_string` to appear exactly once, returns specific errors for 0 matches vs. >1 matches (with the count). For >1 edits on the same file, use MultiEdit.
- MultiEdit is atomic across its edits list — if any edit fails (0 matches or >1 matches without `replace_all`), no write occurs.
- MultiRead batches N file reads into one `conn.exec`; chunks separated by `===FILE: <path>===` markers.
- FileStat uses SFTP's native `stat`, NOT `Bash("stat ...")` — saves channel build, returns structured data.
- Bash with `run_in_background=true` wraps the user command in `setsid nohup bash -c '...' > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`. Returns PID + log path + 4 ready-to-paste command templates (status / read output / stop / force-stop). The `setsid` is **non-optional** — it detaches the background process from the exec channel's session so that closing the channel (timeout/reconnect) does not kill the background process.
- Glob converts `**` patterns to `find -wholename` / `-path` to preserve path-segment semantics; not just `-name <basename>` (which was v1).
- Grep supports `-A/-B/-C` context lines, `head_limit`, `output_mode` (content/files_with_matches/count). Bandwidth win: agent can get matches + surrounding context in one call instead of grep-then-multiple-reads.
- Feedback appends a JSONL entry to `~/.local/share/remote-mcp/feedback.jsonl` (path overridable via top-level `feedback_path` in config). Single `write()` of a JSONL line is POSIX-atomic for typical sizes — multiple per-host processes can write the same file safely. Tool itself does not transmit anywhere; the file is the maintainer's data.

## Project layout

```
remote_mcp/
├── __main__.py        # argparse (--host, --cwd, --config), then asyncio.run(main(...))
├── server.py          # MCP Server, list_tools/call_tool, unified suffix + reconnect-warning dispatch
├── connection.py      # SSHConnection (compress=True, snapshot mgmt, cwd validation), HostConfig, ProxyJump
├── paths.py           # resolve_path(path, cwd) helper for all non-Bash tools
└── tools/
    ├── read.py write.py edit.py multi_edit.py multi_read.py file_stat.py bash.py glob.py grep.py feedback.py
CLAUDE.md.fragment.md  # shipped at repo root; users copy into the LOCAL project's CLAUDE.md (Claude Code reads it at startup — NOT a file on the remote host)
```

`bash_session.py` does **not** exist — it was removed in v0.2.0. There is no persistent bash session, no sentinel protocol, no reader thread.

Config lives in `~/.config/remote-mcp/config.yaml` (overridable with `--config`). See spec §11 for schema (hosts, key_path, jump_host, keepalive_interval, compression, bash_timeout_default, glob_output_limit, read_size_cap, bash_output_cap, default_host).

## Implementation order (completed as of v0.2.0)

Completed bottom-up; per-stage acceptance criteria in v0.2.0 spec §11.

1. `connection.py` — exec, SFTP, ProxyJump, keepalive, **compression=True**, reconnect flag, snapshot mgmt, cwd validation
2. `paths.py` — `resolve_path()` helper
3. File tools: Read (sed-slicing) / Write (SFTP mkdir) / Edit / MultiEdit / **MultiRead** / **FileStat** — all with `resolve_path`
4. Search tools: Glob (`**` via `-wholename`) / Grep (with `-A/-B/-C`, `head_limit`, `output_mode`) — all with `resolve_path`
5. `server.py` + `__main__.py` (`--cwd`) + Bash tool (per-call exec + snapshot wrap, foreground AND **`run_in_background`**) + **Feedback** (local JSONL append) + unified suffix in `call_tool()`
6. Packaging + README + `CLAUDE.md.fragment.md`

## Commands

```bash
pip install -e .
python -m remote_mcp --host <name> [--cwd /opt/app] [--config <path>] [--test]
claude mcp add --scope user remote-<name> -- python -m remote_mcp --host <name> --cwd /opt/app
```

`--cwd` is optional (defaults to remote `$HOME`). It anchors relative paths for all tools and sets the starting directory for each Bash invocation.

## Known limitations baked into the design

Don't "fix" these without checking with the user first — they're explicit scope decisions:

- No interactive/TTY commands (`vim`, `top`, REPLs).
- Text/UTF-8 files only for Write/Edit/MultiEdit; no binary support.
- Edit/MultiEdit are not cross-process atomic — single-agent serial use only.
- Glob `**` semantics are *approximate*, not 100% equivalent to native — run the test cases in the v0.2.0 spec §11 to catch divergences.
- Grep `multiline` parameter intentionally unsupported (POSIX grep limitation; agent should use `awk`/`perl -0` via Bash for multi-line patterns).
- Bash shell state (cwd, env vars, activated venvs) does NOT persist across calls — by design, matching Claude Code native Bash. Chain commands inline: `cd dir && cmd`, `VAR=val cmd`, `venv/bin/python script.py`.
- Each Bash call pays a fresh bash process startup cost (~50-1000ms depending on RTT and remote FS speed). This is the accepted trade-off for matching CC native behavior. Mitigate by batching related commands with `&&`.
- Background bash logs in `/tmp/rmcp-bg-*.log` are not auto-cleaned on server exit (deliberate — leave for post-mortem; `/tmp` reboot cleans).
- Background bash PID reuse is a known low-probability hazard — agent should `kill -0 <pid>` before sending kill signals.
- `~` in tool path arguments is explicitly rejected — use absolute paths or paths relative to the configured cwd.
- cwd sandboxing is not enforced — `../` can escape the configured cwd (same policy as CC native; security boundary is SSH user permissions).
- Cross-host operations (e.g. copy file from prod to gpu) are NOT first-class — out of scope entirely. Use `Bash("scp prod:path gpu:path")` with user-arranged SSH trust.
- Performance not tuned for >3 simultaneous hosts (each runs its own Python process). Federation/plugin form is future work.
- Feedback file is not auto-rotated; maintainer archives manually. No upstream telemetry — purely local dev loop.
