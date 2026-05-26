# remote-mcp

A local Python MCP server that proxies file and shell tools to a remote Linux host over SSH. Claude Code (and any other MCP client) gets 10 tools — Read, Write, Edit, MultiEdit, MultiRead, FileStat, Bash, Glob, Grep, Feedback — all operating on the remote.

## Why

Sometimes the code you want Claude Code to work on lives on a remote server, the server has no agent-installable software, and you only have SSH. This bridges that gap.

## Install

```bash
git clone <repo>
cd remote-mcp
pip install -e .
```

## Configure

Create `~/.config/remote-mcp/config.yaml`:

```yaml
hosts:
  prod:
    hostname: 192.168.1.100
    user: ubuntu
    key_path: ~/.ssh/id_ed25519
    keepalive_interval: 30

default_host: prod
feedback_path: ~/.local/share/remote-mcp/feedback.jsonl
```

See the design spec for the full schema (`docs/superpowers/specs/2026-05-26-remote-mcp-design.md` §11).

## Register with Claude Code

```bash
claude mcp add --global remote-prod -- python -m remote_mcp --host prod
```

Restart Claude Code. The 10 tools appear as `mcp__remote-prod__Read`, etc.

## Recommended: Add the workflow guide

Copy `CLAUDE.md.fragment.md` into your remote project's CLAUDE.md so the agent uses the bandwidth-aware patterns (Grep with context, MultiRead, FileStat, background Bash).

## Smoke test

```bash
python -m remote_mcp --host prod --test
# Expected: Connected to prod (...). All tools: OK
```

## Limitations

See spec §14. Briefly: no TTY commands, text files only, ~3 hosts at a time, Glob `**` is approximate.

## Architecture summary

- 1 Python process per remote host (long-lived, per Claude Code session)
- 1 paramiko Transport per process (compress=on, keepalive=30s)
- Persistent bash channel (sentinel protocol + cwd capture)
- Lazy SFTP for file ops and metadata
- Auto-reconnect once on drop; agent is warned via `[WARNING]` prefix
- Background Bash uses `setsid` for clean process-group kill

Full design: `docs/superpowers/specs/2026-05-26-remote-mcp-design.md`.
