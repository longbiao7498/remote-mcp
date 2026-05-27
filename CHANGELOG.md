# Changelog

All notable changes to remote-mcp are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
