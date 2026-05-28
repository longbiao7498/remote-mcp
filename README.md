# remote-mcp

> 中文版本：[README.zh.md](./README.zh.md)

A local Python MCP server that proxies file and shell tools to a remote Linux host over SSH. Claude Code (and any other MCP client) gets 10 tools — `Read`, `Write`, `Edit`, `MultiEdit`, `MultiRead`, `FileStat`, `Bash`, `Glob`, `Grep`, `Feedback` — all operating on the remote.

When your code lives on a server that only allows SSH, and you don't want to install anything on it, this bridges the gap.

## What makes it different

Other ways to give Claude Code remote access either need software installed on the remote (often not allowed on locked-down prod / GPU / HPC boxes) or work through raw SSH with no MCP integration (no `Read`/`Edit`/`Grep` tools, no persistent shell, terrible bandwidth profile). `remote-mcp` threads that needle:

**🔓 Works anywhere SSH does**
- **Zero install on the remote** — if you can `ssh user@host`, this works. No agent, no daemon, no container, no root needed. Perfect for prod boxes, shared HPC nodes, customer servers you don't admin.
- Pure local Python. Nothing to maintain on the remote side.

**🎯 Tools that feel native to the agent**
- 7 of 10 tools (`Read`, `Write`, `Edit`, `MultiEdit`, `Bash`, `Glob`, `Grep`) match Claude Code's built-in schemas verbatim — same parameters, same output formats, same error wording. The agent uses them naturally; no retraining, no "remote mode" prompt engineering needed.
- Multi-host first-class: each registered host is its own `mcp__remote-<name>__` namespace. The agent knows what's where.

**⚡ Built for slow / lossy networks** (the design hinges on this)
- **Server-side `sed` slicing for `Read`** — fetching 20 lines from a 100 MB file transfers a few KB, not 100 MB.
- **SSH compression on by default** — 3-10× savings on text, free.
- **`MultiRead`** batches N file reads into one round-trip; **`MultiEdit`** does N edits with one read + one write.
- **`Grep -A/-B/-C` context** — agent doesn't need a follow-up `Read` to see surrounding code.
- **`FileStat`** returns metadata in a few bytes (vs `Read`-ing the file just to check existence/size).
- **Background `Bash`** (`run_in_background=true`) — start a 10-min build / `npm install` / training run without blocking the agent's conversation.

**🛡 Survives the messy parts of remote work**
- **Configurable remote `cwd` (`--cwd /opt/app`)** — tools accept relative paths; they resolve against the configured working directory. Default is remote `$HOME`.
- **Auto-reconnect with explicit warning** — when SSH drops (VPN blip, idle timeout), connection rebuilds automatically AND the next tool result is prefixed with `[WARNING] SSH connection to <host> was lost ...`. Agent doesn't silently keep using stale paths.
- **Clean process-group kill for background jobs** — `kill -- -<pid>` takes down spawned children too (the wrapper uses `setsid`).

**🔁 Self-improving dev loop**
- A built-in `Feedback` tool lets the agent file bug/enhancement notes about `remote-mcp` itself, into a local JSONL — no telemetry, purely a maintainer-readable file. Two of the changes in the current [Unreleased] window (Grep skipping binaries, Edit listing line numbers in errors) came directly from agent feedback during testing.

## Requirements

- Python 3.8+
- An SSH-reachable Linux host (you can already `ssh user@host` without a password prompt)
- Claude Code installed locally (or another MCP client)

## Install

```bash
git clone https://github.com/longbiao7498/remote-mcp.git
cd remote-mcp
pip install -e .
```

This is a pure-Python package — there's no compile step. `pip install` pulls in `paramiko`, `mcp`, and `pyyaml`.

## Configure

Create `~/.config/remote-mcp/config.yaml`:

```yaml
hosts:
  myserver:
    hostname: 192.168.1.100
    user: alice
    key_path: ~/.ssh/id_ed25519

default_host: myserver
```

That's all you need to start. The full schema (multi-host, ProxyJump, per-host tuning) is in [`docs/reference/config-schema.md`](./docs/reference/config-schema.md).

## Verify

```bash
python -m remote_mcp --host myserver --test
```

Expected output:

```
Connected to myserver (alice@192.168.1.100). All tools: OK
```

If you see this, the SSH connection works and `remote-mcp` is healthy. If you get an error, see [the disconnect troubleshooting guide](./docs/how-to/recover-from-disconnect.md).

## Register with Claude Code

One `claude mcp add` per host:

```bash
claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod --cwd /opt/myapp
```

Restart Claude Code. Ten new tools will appear in the tool list, namespaced as `mcp__remote-myserver__Read`, `mcp__remote-myserver__Bash`, and so on. Ask the agent something like *"use the remote tools to show me /etc/hostname"* and you'll see them in action.

> **What's user-chosen vs. what's fixed CLI syntax** — important to separate, because the command has two user-chosen tokens that *happen* to look identical in this example.
>
> Schema:
>
> ```
> claude mcp add --scope user  <NAMESPACE>  --  python -m remote_mcp --host  <HOST-KEY>
> └─── fixed Claude Code CLI ──┘└─you─┘  ↑   └─── fixed remote-mcp CLI ──┘└─you─┘
>                              choose   │                                 choose
>                                       └ separator: "everything after this is the command to run"
> ```
>
> The two **you-choose** tokens are independent:
>
> - **`<NAMESPACE>`** — the label Claude Code uses to identify this MCP server. It becomes the **tool prefix** the agent sees: `mcp__<NAMESPACE>__Read`, `mcp__<NAMESPACE>__Bash`, etc. Also the name you use later with `claude mcp remove <NAMESPACE>` and `claude mcp list`. Anything alphanumeric + dashes works.
> - **`<HOST-KEY>`** — the key under `hosts:` in your `~/.config/remote-mcp/config.yaml`. Tells `remote-mcp` *which* remote to SSH into. Must match exactly.
>
> Everything else in the command (`claude mcp add`, `--scope user`, `--`, `python -m remote_mcp`, `--host`) is **fixed CLI syntax** — type it verbatim.
>
> **Two concrete examples:**
>
> ```bash
> # Recommended (matching names — least confusing):
> claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
> # Agent sees: mcp__remote-prod__Read, ..., all operating on the 'prod' host
>
> # Also valid (mismatched — unusual but works):
> claude mcp add --scope user box42 -- python -m remote_mcp --host gpu-server-01
> # Agent sees: mcp__box42__Read, ..., all operating on the 'gpu-server-01' host
> ```
>
> **Convention**: prefix `<NAMESPACE>` with `remote-` (so the namespace stands out from any local MCP servers) and set it to `remote-<HOST-KEY>` (so the namespace tells you which remote). See [Configure multiple remote hosts](./docs/how-to/configure-multi-host.md) for the multi-host story.

## Recommended: Add the workflow guide

The agent uses remote tools more efficiently when it knows about the bandwidth-aware patterns (Grep with context lines instead of grep-then-read, MultiRead instead of consecutive Read, background Bash instead of blocking on long jobs). Copy [`CLAUDE.md.fragment.md`](./CLAUDE.md.fragment.md) into the `CLAUDE.md` of your **local** project (the one Claude Code reads at session startup — *not* a file on the remote host). See [Use the CLAUDE.md workflow fragment](./docs/how-to/use-the-workflow-fragment.md) for the three usage patterns (per-project, user-level, team-shared).

## Where to go next

All documentation lives under [`docs/`](./docs/), organized along the [Diátaxis](https://diataxis.fr/) framework — pick the entry point that matches what you need:

| | I want to... | Read |
|---|---|---|
| 📘 | **walk through a complete first session** with hand-holding | [`docs/tutorial/first-remote-session.md`](./docs/tutorial/first-remote-session.md) |
| 🛠 | **solve a specific problem** (multi-host, slow networks, MCP not appearing, ...) | [`docs/how-to/`](./docs/how-to/) |
| 📚 | **look up exact parameters, errors, or config** | [`docs/reference/`](./docs/reference/) |
| 💡 | **understand the design** (why paramiko, why persistent bash, why the WARNING text...) | [`docs/explanation/`](./docs/explanation/) |

Every page is bilingual — every `name.md` has a `name.zh.md` sibling.

## Project status

v0.2.0 — see [`CHANGELOG.md`](./CHANGELOG.md) for what's in this release and [`docs/superpowers/specs/`](./docs/superpowers/specs/) for the original design.

## License

MIT — see [`LICENSE`](./LICENSE).

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) and the developer how-to: [add a new tool](./docs/how-to/add-a-new-tool.md).
