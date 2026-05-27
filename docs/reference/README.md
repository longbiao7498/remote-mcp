# Reference

> 中文版本：[`README.zh.md`](./README.zh.md)

Reference documentation **describes the machinery**: parameter lists, return formats, configuration schemas, error catalogs. It is precise, neutral, and complete.

A reference page is *not* a tutorial (no narrative) and not a how-to (no advice — just facts). Read it when you need to look something up.

## Tool reference

One page per tool exposed by remote-mcp. Each page documents: full parameter schema, return format, error wording, behavior notes, bandwidth/latency characteristics.

| Tool | Purpose |
|------|---------|
| [Read](./tools/read.md) | Read lines from a remote file (server-side `sed` slicing) |
| [Write](./tools/write.md) | Write content to a remote file (creates parent dirs via SFTP) |
| [Edit](./tools/edit.md) | Replace an exact string in a remote file (uniqueness checked) |
| [MultiEdit](./tools/multi-edit.md) | Apply multiple edits to one file atomically |
| [MultiRead](./tools/multi-read.md) | Batch-read multiple remote files in one round-trip |
| [FileStat](./tools/file-stat.md) | Get metadata (existence, size, mtime, mode) without transferring content |
| [Bash](./tools/bash.md) | Execute a shell command (persistent state; foreground or background) |
| [Glob](./tools/glob.md) | Find files matching a glob pattern (server-side `find`) |
| [Grep](./tools/grep.md) | Search file contents for a regex (server-side `grep` with context support) |
| [Feedback](./tools/feedback.md) | Record a local bug/enhancement note about remote-mcp itself |
| [Upload](./tools/upload.md) | Push a local file to the remote via SFTP (binary-safe). Windows convenience; Linux prefers Bash + scp. |
| [Download](./tools/download.md) | Pull a remote file to local via SFTP (binary-safe). Windows convenience; Linux prefers Bash + scp. |
| [RemoteInfo](./tools/remote-info.md) | Return the connection's configured identity (host, user, hostname, port, jump_host). No SSH call — VPN-safe. |

## System reference

| Page | Covers |
|------|--------|
| [Configuration schema](./config-schema.md) | All fields in `~/.config/remote-mcp/config.yaml` |
| [CLI](./cli.md) | `python -m remote_mcp` arguments and exit codes |
| [Error wording catalog](./errors.md) | All `"Error: ..."` strings tools return, with triggering conditions |

## What goes in reference (for contributors)

- Describe the system *as it is*, not as you wish it were. If behavior is surprising, document the surprise — don't apologize for it.
- Structure must be predictable. Same headings in same order on every tool page.
- No tutorials, no opinions, no advice. Cross-link to how-to / explanation for those.
- Code blocks are facts (real CLI output, real schemas, real error strings — verbatim).
- Updates are mandatory when behavior changes. Reference that lies is worse than no reference.
