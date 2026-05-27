# remote-mcp

> 中文版本：[README.zh.md](./README.zh.md)

A local Python MCP server that proxies file and shell tools to a remote Linux host over SSH. Claude Code (and any other MCP client) gets 10 tools — `Read`, `Write`, `Edit`, `MultiEdit`, `MultiRead`, `FileStat`, `Bash`, `Glob`, `Grep`, `Feedback` — all operating on the remote.

When your code lives on a server that only allows SSH, and you don't want to install anything on it, this bridges the gap.

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
claude mcp add --scope user remote-myserver -- python -m remote_mcp --host myserver
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

The agent uses remote tools more efficiently when it knows about the bandwidth-aware patterns (Grep with context lines instead of grep-then-read, MultiRead instead of consecutive Read, background Bash instead of blocking on long jobs). Copy [`CLAUDE.md.fragment.md`](./CLAUDE.md.fragment.md) into your remote project's `CLAUDE.md` so the agent picks up these rules automatically.

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

v0.1.0 — see [`CHANGELOG.md`](./CHANGELOG.md) for what's in this release and [`docs/superpowers/specs/`](./docs/superpowers/specs/) for the original design.

## License

MIT — see [`LICENSE`](./LICENSE).

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) and the developer how-to: [add a new tool](./docs/how-to/add-a-new-tool.md).
