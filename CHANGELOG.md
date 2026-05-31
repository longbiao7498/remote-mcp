# Changelog

> 中文版本：[CHANGELOG.zh.md](./CHANGELOG.zh.md)

All notable changes to remote-mcp are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-05-31

### Background task panel

v0.3.0 introduces a first-class background task panel: a persistent, named, queryable registry of background jobs launched via `Bash(run_in_background=True)`. Agents can now name jobs, list their states, attach status scripts, kill them, and archive them — all without writing boilerplate `pgrep`/`tail`/`kill` chains. Design rationale and architecture in `docs/explanation/job-panel.md`.

### Added — four new panel tools (total tool count 13 → 17)

- **`Jobs(name=X | id=N | filter=F)`** — query the panel. List mode returns all active jobs with live state; single-task mode additionally runs an optional status script. Filter values: `stopped_unprocessed` (finished tasks awaiting result review), `stuck_kill` (tasks resisting kill after ≥ 3 attempts), `zombies` (tasks archived as given-up). State machine: `running` / `stopped` / `killed` / `kill_failed`. Terminal states (`stopped`, `killed`) are not re-observed after first confirmation — avoids PID-reuse false positives.

- **`JobKill(name=X | id=N [, kill_cmd=...])`** — issue one kill command and verify liveness in a single packed exec (5 s timeout). Records the attempt in `kill_attempts[]` and updates state. Two-tier escalation warnings: L1 when a single task has ≥ 3 failed attempts; L2 when the host has ≥ 5 stuck tasks.

- **`JobArchive(name=X | id=N [, as_zombie=True])`** — purely local operation (zero remote ops). Moves `<id>-meta.json` (and `<id>-status.sh` if present) to `archive/` (stopped/killed tasks) or `zombie/` (kill_failed tasks acknowledged as gave-up). Requires state to be terminal; guards against archiving running or unconfirmed tasks. Zombie escalation warning at ≥ 5 zombie count.

- **`JobScript(name=X | id=N, script="...", timeout=N)`** — attach a custom bash status script to a job. Script is stored locally as the source of truth and uploaded to the remote as a cache; `Jobs(name=X)` single-task mode runs it automatically. First-run validation at attach time: timeout triggers rejection and cleanup; non-zero exit is accepted with a notice. Pass `script=""` to clear.

### Added — Bash `run_in_background=True` extensions

- **`log_path`** parameter: explicit remote log path for the background task's stdout+stderr. Defaults to `~/.cache/remote-mcp-<sid>-<id>.log` (persists across reboots unlike `/tmp`). Parent dirs auto-created via `mkdir -p`.
- **`name`** parameter: human-readable job alias for panel reference. Must be unique among active jobs. Defaults to `bg-<uuid12>`.
- **Structured return**: background launch now returns `id / name / log_path / pid / started_at` instead of the old four-line hint template. Panel tools replace the raw `kill`/`Read` templates.
- **Synchronous PID confirmation at launch**: if the exec response is lost (network fault), the tool immediately falls back to SFTP-read of the remote pid file. If both fail, the task is NOT entered into the panel and an explicit Error is returned with recovery instructions.

### Added — local-first metadata storage

- Panel metadata and status script sources live on the MCP host at `~/.local/share/remote-mcp/jobpane/<sid>/<host>/`. Remote retains only flat-named files: `~/.cache/remote-mcp-<sid>-<id>-pid`, `~/.cache/remote-mcp-<sid>-<id>-status.sh`, and the log.
- `<sid>` is derived from `PPID + parent-process start_time` via `psutil` so that MCP server restarts within the same Claude Code session preserve the panel.
- IDs are session+host-scoped monotonically increasing integers allocated with `fcntl` flock; name reuse after archive is safe (old and new tasks get different IDs).

### Added — infrastructure

- `exec_with_snapshot(conn, command, timeout) -> ExecResult` helper extracted from `_bash_foreground`; shared by all panel tools and Bash.
- `remote_mcp/jobs/` package: `sid.py`, `paths.py`, `init.py`, `meta.py`, `state.py`, `scripts.py`, `constants.py`.
- `RemoteInfo` output now includes `sid=<value>`.
- `BASH_DESC` rewritten to expose the actual shell wrap generated for both foreground and background modes.
- `psutil>=5.9` added as a dependency.

### Known limitation

Panel state does not survive Claude Code restart (new CC process → new PPID → new sid → old panel directory is not visible). Tasks still run on remote. Recovery: `Bash("ls ~/.cache/remote-mcp-*-pid")` lists all remote pid files across sessions; cross-reference with old `sid` values visible in the file names.

## [0.2.2] — 2026-05-28

### Network robustness — unified behavioral contract

All four fixes below address the same root design gap: network failure was not a first-class concern in earlier versions, and individual tools handled it ad-hoc. v0.2.2 establishes three behavioral contracts (bounded-time return, distinguishable success/failure, no false reporting) enforced at the framework level. Per-tool code is essentially unchanged.

### Added
- `HostConfig.op_timeout_default` (default 60s): idle timeout applied to all SFTP and exec channels via `channel.settimeout`. Prevents silent SFTP hangs during laptop suspend (bug #2).
- `server.NO_RETRY_TOOLS` (`{Edit, MultiEdit, Bash}`): tools in this set bypass `_with_retry` and route through a new `_with_reconnect_only` helper. SSH failures trigger reconnect but the original error is returned to agent — no transparent re-execution.
- Local in-memory snapshot cache: captured once at MCP startup, persisted to remote `~/.cache/remote-mcp/snapshot-<pid>.sh`. Reconnect re-uploads from cache only if remote file is missing; never re-runs `bash -ic` (bashrc changes mid-session are deliberately not picked up, matching Claude Code native).
- Background bash pidfile: `_bash_background` writes PID to `/tmp/rmcp-bg-<uuid>.pid` before echoing `BG_PID`. Even if the echo response is lost, agent can `Bash("cat /tmp/rmcp-bg-*.pid")` to recover orphan PIDs (bug #3).

### Changed
- Edit and MultiEdit no longer auto-retry on SSH-layer failure (bug #1). Read-modify-write tools that successfully wrote on remote could otherwise return a false `old_string not found` after retry. Agent now sees `Error: <SSHException>: ...` and decides whether to re-issue.
- Bash also no longer goes through `_with_retry` for its SSH-layer failures (Bash channel-death handling from v0.2.1 unchanged).
- Reconnect WARNING text now has three variants: (A) normal reuse without snapshot mention; (B) "remote snapshot was missing and has been re-uploaded from local cache"; (C) "re-upload failed, subsequent Bash will run without PATH/aliases" (bug #4).
- New "session-start snapshot capture failed" WARNING shown once on first tool call after a failed initial snapshot capture.
- Snapshot file location moves from `/tmp/rmcp-snapshot-<host>-<pid>.sh` to `~/.cache/remote-mcp/snapshot-<pid>.sh` to avoid `/tmp` cleanup.
- `close()` no longer deletes the remote snapshot file (it persists in `~/.cache/`).
- `connect()` no longer calls snapshot capture; capture is now triggered once by `server.main()` at startup.

## [0.2.1] — 2026-05-28

### Fixed
- **Bash channel-death now surfaces clearly** instead of returning opaque `[Exit code: -1]`. When the SSH transport dies mid-call (e.g. laptop suspend, network drop), `Bash` now returns `Error: SSH channel to <host> closed unexpectedly during command (transport likely disconnected ...). The next tool call will trigger reconnect. Re-run this command only if it is safe to repeat.` The next tool call triggers normal `_with_retry` reconnect. We deliberately do NOT auto-retry the failed command — agent decides whether re-running is safe (non-idempotent commands like `rm`, `migrate`, etc. shouldn't be silently re-run).
- **Drain loop exception scope tightened**: `_bash_foreground` polling loop now catches only `socket.timeout` (the expected `channel.settimeout` poll signal) rather than blanket `Exception`. Defensive: prevents future paramiko-version changes from accidentally hiding `socket.error` / `EOFError` / `SSHException` from a dead channel.

## [0.2.0] — 2026-05-27

### BREAKING CHANGES
- **Non-persistent Bash**: shell state (cwd, env, source'd venvs) no longer persists across Bash calls. Use `cd dir && cmd`, `FOO=bar cmd`, `venv/bin/python script.py` for inline state. Aligns with Claude Code native behavior.
- **Output format**: every tool's output now ends with `\n\n[host=X cwd=Y]` (was Bash-only `[host=X cwd=Y]\n` prefix in v0.1.x; now uniformly applied as suffix by the MCP server). Scripts that parse exact byte offsets need updating.
- **Glob/Grep output paths**: default `path="."` now resolves to the configured cwd → output is absolute paths (`/opt/app/foo.py`), not relative (`./foo.py`). Aligns with Claude Code native.

### Added
- `--cwd <path>` CLI flag and `hosts.<name>.cwd` YAML field — anchor relative paths in all tools (`Read("config.yaml")` → `<cwd>/config.yaml`). Default = remote `$HOME`. Format must be `/...`, `~`, or `~/...`; invalid format fails fast at startup. Tilde expanded at connect time. Existence validated via SFTP stat — bad cwd → MCP server refuses to start.
- `remote_mcp/paths.py` with `resolve_path(path, cwd)` helper.
- `RemoteInfo` output now includes `cwd=<value>` line.

### Removed
- `remote_mcp/bash_session.py` (persistent shell + sentinel protocol — replaced by per-call exec + snapshot replay).
- `SSHConnection.get_bash_session()`.

### Changed
- Reconnect WARNING simplified to: `[WARNING] SSH connection to <host> was lost and has been re-established. Snapshot was rebuilt; if your bashrc has changed since the connection started, the new state takes effect from this point.`
- Bash timeout now uses `channel.close()` (SIGHUP via channel close) instead of Ctrl-C via PTY. Partial stdout collected before timeout is included in the error output.

## [0.1.1] - Unreleased

### Changed

Driven by agent feedback (the `Feedback` tool's first real-use entries — see `~/.local/share/remote-mcp/feedback.jsonl`):

- **Grep skips binary files by default.** Added `-I` to the always-on grep flags. Binary artifacts (ELF executables, vim swap files, archives) used to show up in matches and pollute output; now they're silently excluded. Matches the behavior of native Claude Code Grep (which uses ripgrep). No new parameter — if binary search is genuinely needed, use Bash directly. *Reported by agent on host `tjcs_ln5` after seeing `printf` matches in an ELF binary and a `.swp` file.*

- **Edit and MultiEdit `found N times` error now lists matching line numbers.** Wording was previously: `Error: old_string found 3 times in <path>. Provide more context to match uniquely, or set replace_all=true to replace all.` It's now: `Error: old_string found 3 times in <path> (lines 19, 20, 21). Provide more context to match uniquely, or set replace_all=true to replace all.` Lists are capped at the first 10 matches, then suffix `..., ... +K more`. Saves the agent a follow-up Grep when it intended a unique replace. Same enhancement applied to MultiEdit's per-edit error. *Suggested by agent during the same test session.*

### Added — Three new tools (count 10 → 13)

- **`Upload(local_path, remote_path)`** — push a local file to the remote via SFTP. Binary-safe. Preflight checks for existence, type (must be a file), and size (must be ≤ `transfer_size_cap`). Parent directories on the remote are auto-created. For Linux/macOS, the tool description and oversized-file error both steer the agent to `Bash("scp ...", run_in_background=true)` instead — non-blocking, no size limit, resumable. Upload is the Windows-without-scp fallback.

- **`Download(remote_path, local_path)`** — pull a remote file to local via SFTP. Symmetric to Upload (same cap, same scp guidance). Pre-checks remote existence and size via SFTP `stat`. Local parent directory must already exist (not auto-created — asymmetric with Upload).

- **`RemoteInfo()`** — return the connection's configured identity in 5 `key=value` lines (`host`, `user`, `hostname`, `port`, `jump_host`). **Issues no SSH call** — reads `conn.config`. VPN-safe: in VPN scenarios the remote's `hostname -I` returns internal-network IPs that don't match the IP the client uses; this tool returns the latter.

### Added — config

- `HostConfig.transfer_size_cap` — int, default `100 * 1024 * 1024` (100 MB). Caps `Upload` / `Download` per-file size. Files larger return an `Error: ...` with a ready-to-paste `Bash + scp` command.

### Changed — guidance

- `CLAUDE.md.fragment.md`: new rule advising agents to prefer `Bash + scp` for transfers on Linux/macOS; Upload/Download positioned explicitly as Windows fallback.

### Notes

The class of bug found in pre-release docs is also documented for posterity: the doc-writing pass mistakenly invented several external-tool specifics (a `--global` flag, a `/tools` slash command, the `~/.claude/logs/` log path, a fabricated multi-line `--test` output). All were caught by an expert audit and corrected; the corrections are in this same `[0.1.1]` window. The lesson informs the project's writing convention going forward: any CLI / path / output-format claim about an external tool must be verified by running the command, reading source, or fetching docs — not guessed.

## [0.1.0] - 2026-05-26

Initial release. Implements the v2 design spec in full.

### Added

**Ten MCP tools** exposed over stdio, all operating on a remote Linux host via SSH:

- `Read` — read a remote file (server-side `sed` slicing; only the requested
  lines cross the wire)
- `Write` — write a file (SFTP-native recursive `mkdir`)
- `Edit` — uniqueness-checked single-string replacement
- `MultiEdit` — atomic multi-edit on a single file (1 read + 1 write for any
  number of edits)
- `MultiRead` — batch-read N files in one round-trip
- `FileStat` — metadata lookup (existence, size, mtime) without transferring
  file content
- `Bash` — persistent shell with `[host=X cwd=Y]` prefix; `run_in_background=true`
  returns PID + log path for clean process-group kills (`setsid` wrapping)
- `Glob` — `find`-backed pattern search; `**` approximated via `-wholename`
- `Grep` — context lines (`-A`/`-B`/`-C`), `head_limit`, `output_mode`
  (content / files_with_matches / count)
- `Feedback` — local JSONL append for agent-filed dev-loop notes
  (bugs / enhancements)

**Connection infrastructure**:
- One paramiko Transport per MCP server process (compress=on, keepalive=30s)
- Multiplexed channels: persistent bash + lazy SFTP + ephemeral exec
- Auto-reconnect once on SSH drop; subsequent tool calls prefixed with
  `[WARNING] SSH connection to <host> was lost ...`
- Optional ProxyJump via `open_channel("direct-tcpip", ...)`

**Bash session**:
- Sentinel protocol captures exit code AND `pwd` in a single round-trip
- PTY allocation so `\x03` (Ctrl-C) actually delivers SIGINT to the foreground
  process — enables timeout-without-killing-session
- Background reader thread (mandatory; prevents remote bash from blocking on
  buffer-full)

**CLI**:
- `python -m remote_mcp --host <name>` (stdio MCP loop)
- `--config <path>` (default `~/.config/remote-mcp/config.yaml`)
- `--test` (smoke-test reachability, exit)

### Known Limitations

See spec §14. Highlights:
- No interactive/TTY commands (vim, top, REPLs)
- Text/UTF-8 only for Write/Edit/MultiEdit
- Glob `**` is approximate, not 100% equivalent to native
- Grep `multiline` intentionally unsupported (POSIX grep limitation)
- ProxyJump integration test skipped on the dev host (AllowUsers ACL blocks
  self-jump); code is correct, just not end-to-end tested
- Cross-host operations not first-class — use `Bash("scp host_a:p host_b:p")`

### Not Yet Implemented

See spec §15 for future work — primarily:
- Claude Code plugin form factor (would auto-install the M2 workflow guide
  as an always-on skill and expose `/remote-add`, `/remote-cd`, etc.)
- Read streaming for files > 100 MB
- Background Bash log auto-rotation

[0.1.0]: https://github.com/longbiao7498/remote-mcp/releases/tag/v0.1.0
