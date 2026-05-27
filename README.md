# remote-mcp

A local Python MCP server that proxies file and shell tools to a remote Linux host over SSH. Claude Code (and any other MCP client) gets 10 tools — `Read`, `Write`, `Edit`, `MultiEdit`, `MultiRead`, `FileStat`, `Bash`, `Glob`, `Grep`, `Feedback` — all operating on the remote.

## Why

Sometimes the code you want Claude Code to work on lives on a remote server, the server has no agent-installable software, and you only have SSH. This bridges that gap.

## Install

```bash
git clone <repo>
cd remote-mcp
pip install -e .
```

Requires Python 3.8+. Pulls in `paramiko`, `mcp`, `pyyaml`.

## Configure

Create `~/.config/remote-mcp/config.yaml`. **Minimal** (single host):

```yaml
hosts:
  prod:
    hostname: 192.168.1.100
    user: ubuntu
    key_path: ~/.ssh/id_ed25519

default_host: prod
```

**Full example** (multiple hosts, ProxyJump, all tuning knobs):

```yaml
hosts:
  jump:
    hostname: jump.example.com
    user: ops
    port: 2222
    key_path: ~/.ssh/jump_key

  prod:
    hostname: 10.0.0.50         # only reachable from jump
    user: ubuntu
    key_path: ~/.ssh/id_ed25519
    jump_host: jump             # → routes via the 'jump' host above
    keepalive_interval: 60      # default 30s; raise if VPN doesn't enforce strict idle timeouts
    compression: true           # default true; turn off only for already-compressed transfers
    bash_timeout_default: 300   # default 120; raise for slow links
    glob_output_limit: 2000     # default 1000
    read_size_cap: 524288       # default 256 KB
    bash_output_cap: 204800     # default 100 KB

  gpu:
    hostname: 10.0.0.60
    user: longbiao
    key_path: ~/.ssh/id_ed25519

default_host: prod
feedback_path: ~/.local/share/remote-mcp/feedback.jsonl
```

Full schema: design spec §11 (`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`).

## Register with Claude Code

One `claude mcp add` per host:

```bash
claude mcp add --global remote-prod -- python -m remote_mcp --host prod
claude mcp add --global remote-gpu  -- python -m remote_mcp --host gpu
```

Restart Claude Code. Tools appear as `mcp__remote-prod__Read`, `mcp__remote-gpu__Bash`, etc.

## Recommended: Add the workflow guide

Copy `CLAUDE.md.fragment.md` into your remote project's CLAUDE.md so the agent uses the bandwidth-aware patterns (Grep with context, MultiRead, FileStat, background Bash, multi-host hygiene).

Without this guide, the agent will tend to fall back to read-then-grep, edit-edit-edit, blocking Bash — costing many round-trips on slow links.

## Smoke test

```bash
python -m remote_mcp --host prod --test
# Expected: Connected to prod (ubuntu@192.168.1.100). All tools: OK
```

Exit code 0 = healthy. Non-zero = connection or auth problem (see Troubleshooting below).

## What tool calls look like

**Read** returns numbered lines (matching Claude Code's native Read):

```
     1	#!/usr/bin/env python3
     2	import sys
     3	
     4	def main():
```

**Bash** prefixes results with the host + working directory:

```
[host=prod cwd=/opt/app]
build/main.o
build/util.o
[Exit code: 0]
```

**Bash with `run_in_background=true`** returns immediately:

```
[host=prod cwd=/opt/app]
Started background task.
  PID: 12345
  Log: /tmp/rmcp-bg-abc123def456.log

To check status:    Bash("kill -0 12345 && echo running || echo done")
To read new output: Read("/tmp/rmcp-bg-abc123def456.log", offset=<last_line+1>)
To stop gracefully: Bash("kill -TERM -- -12345")
To force stop:      Bash("kill -KILL -- -12345")
```

**After a network blip / VPN drop**, the next tool result is prefixed with:

```
[WARNING] SSH connection to prod was lost and has been re-established. The
remote bash session has been reset: working directory is now $HOME, all
environment variables set in previous commands are lost. Use absolute paths
and re-run any necessary setup commands.

... (normal tool output below)
```

## The `Feedback` tool

`remote-mcp` ships a 10th tool — `Feedback` — that lets the agent file dev-loop notes (bugs / enhancements about the remote-mcp tools themselves) to a local JSONL file as it works. The maintainer reads it to drive iteration grounded in real usage.

- File: `~/.local/share/remote-mcp/feedback.jsonl` (configurable)
- Never transmitted anywhere — purely local
- The workflow guide in `CLAUDE.md.fragment.md` tells the agent when to use it

To inspect what your agent has filed:

```bash
cat ~/.local/share/remote-mcp/feedback.jsonl | jq .
```

## Troubleshooting

**`Connected but echo failed`** during `--test`
- The SSH handshake succeeded but the remote sshd refuses to execute commands. Check sshd config (`ForceCommand`, `AllowUsers`) or login shell.

**`pip install` succeeds but `python -m remote_mcp --help` says "No module named remote_mcp"**
- You ran `pip install` against a different Python than `python -m` invokes. Try `python -m pip install -e .` to force them to the same interpreter.

**Claude Code doesn't show the tools after `claude mcp add`**
- Restart Claude Code (the tool list is loaded at startup).
- Check the MCP server starts: `python -m remote_mcp --host prod` should hang waiting for stdio (Ctrl-C to exit). If it errors immediately, fix the error first.

**SSH key requires a passphrase**
- v0.1.0 doesn't yet support passphrase prompts. Use `ssh-agent` (`ssh-add ~/.ssh/your_key`) and remove `key_path` from config so paramiko uses the agent.

**`[WARNING] SSH connection ... was lost` appears repeatedly**
- Underlying link is unstable. Lower `keepalive_interval` (e.g. to 15) so paramiko detects drops faster and reconnects sooner.

**Background bash logs piling up in `/tmp/rmcp-bg-*.log`**
- By design — they're left for post-mortem. Clean manually with `ssh host 'rm /tmp/rmcp-bg-*.log'` or wait for `/tmp` reboot cleanup.

**Glob `**` doesn't match what I expect**
- `**` is approximated via `find -wholename` (collapsed to `*`). For complex path patterns, use Bash with `find` directly. See spec §14.

## Limitations

See spec §14. Briefly:

- No interactive / TTY commands (vim, top, REPLs)
- Text / UTF-8 files only for Write / Edit / MultiEdit (no binary)
- Glob `**` is approximate, not 100% equivalent to native
- Grep `multiline` intentionally unsupported
- Designed for 2-3 simultaneous hosts; 10+ hosts not performance-tuned
- Background bash PID reuse is a low-probability hazard (always `kill -0 <pid>` first)
- Cross-host operations not first-class — use `Bash("scp host_a:p host_b:p")` with pre-arranged SSH trust

## Architecture summary

- 1 Python process per remote host (long-lived, per Claude Code session)
- 1 paramiko Transport per process (compress=on, keepalive=30s)
- Persistent bash channel (sentinel protocol + cwd capture, PTY-allocated)
- Lazy SFTP for file ops and metadata
- Ephemeral exec channels for Glob/Grep/MultiRead/Read sed-slicing
- Auto-reconnect once on drop; agent is warned via `[WARNING]` prefix
- Background Bash uses `setsid` for clean process-group kill

Full design: `docs/superpowers/specs/2026-05-26-remote-mcp-design.md`.  
Implementation history: `docs/superpowers/plans/2026-05-26-remote-mcp-implementation.md`.

## License

MIT — see `LICENSE`.

## Contributing

See `CONTRIBUTING.md` for project layout, dev setup, test instructions, and how to add a new tool.
