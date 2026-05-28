# Changelog

> 中文版本：[CHANGELOG.zh.md](./CHANGELOG.zh.md)

All notable changes to remote-mcp are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
