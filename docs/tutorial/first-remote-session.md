# Your first remote session

> 中文版本：[first-remote-session.zh.md](./first-remote-session.zh.md)

This tutorial takes you from a fresh `git clone` to Claude Code successfully reading a file on your remote server — using remote-mcp tools. It takes about 15 minutes.

You will install remote-mcp locally, write one config file, verify the SSH connection, register the server with Claude Code, and watch the agent call `mcp__remote-myserver__Read` for the first time.

---

## Before you begin

Make sure you have all four of these in place before starting. If any are missing, this tutorial will not work.

- **Python 3.8 or newer** on your local machine.
  ```bash
  python --version
  ```
  You should see something like `Python 3.11.4`. If you get `command not found`, install Python first.

- **A remote Linux host you can SSH into.** You must be able to run this and get a shell:
  ```bash
  ssh user@your-host.example.com
  ```
  If this doesn't work yet, fix your SSH setup before continuing. remote-mcp cannot do this for you.

- **Claude Code installed and working.** Running `claude --version` should print a version number.

- **An SSH key (not a password).** The tutorial uses key-based auth. If your current `ssh user@host` uses a password, add your public key to `~/.ssh/authorized_keys` on the remote host first.

---

## Step 1 — Clone and install

On your **local** machine, clone the repository and install it in editable mode.

```bash
git clone https://github.com/your-org/remote-mcp.git
cd remote-mcp
pip install -e .
```

You should see pip resolve and install three dependencies — `paramiko`, `mcp`, and `pyyaml` — and then finish with something like:

```
Successfully installed mcp-... paramiko-... pyyaml-... remote-mcp-0.1.0
```

Confirm the package is importable:

```bash
python -m remote_mcp --help
```

You should see:

```
usage: remote_mcp [-h] --host HOST [--config CONFIG] [--test]
...
```

If you see this, the install worked.

---

## Step 2 — Write a minimal config file

Create the config directory and open a new file:

```bash
mkdir -p ~/.config/remote-mcp
```

Now create `~/.config/remote-mcp/config.yaml` with the following content. Replace the three values (`myserver`, `your-host.example.com`, `alice`, `~/.ssh/id_ed25519`) with your actual host details.

```yaml
hosts:
  myserver:
    hostname: your-host.example.com
    user: alice
    key_path: ~/.ssh/id_ed25519
    cwd: ~/projects/myapp

default_host: myserver
```

That is the complete minimal config. The `cwd` field sets the working directory all tools use when resolving relative paths — omit it to default to the remote `$HOME`. Save the file.

> **Note on the host label:** `myserver` is the name you choose — it appears in the tool names Claude Code will call (`mcp__remote-myserver__Read`). Use a short, slug-friendly name (letters, digits, hyphens). We use `myserver` throughout this tutorial; substitute your own wherever you see it.

---

## Step 3 — Smoke-test the connection

Run the built-in test. It does a quick end-to-end probe: connect over SSH, run `echo OK` on the remote, confirm the result.

```bash
python -m remote_mcp --host myserver --test
```

You should see exactly one line:

```
Connected to myserver (alice@your-host.example.com). All tools: OK
```

(`All tools: OK` is a fixed string the test prints when the probe succeeds — it doesn't mean every individual tool was exercised; the real test of each tool happens when you call it from Claude Code in Step 6.)

If you see this line, the SSH side is healthy and you're ready to register.

If you see an error instead, stop here. Check that `ssh alice@your-host.example.com` works from the same terminal session before continuing. Common fixes are in the [Troubleshooting how-to](../how-to/debug-mcp-not-appearing.md).

---

## Step 4 — Register with Claude Code

Run `claude mcp add` to register this host as an MCP server. The `--scope user` flag (vs the default `--scope local`) makes it available in every Claude Code project, not just the one you're currently in.

```bash
claude mcp add --scope user remote-myserver -- python -m remote_mcp --host myserver
```

The command prints a short confirmation that the server was added (exact wording varies by Claude Code version). That's all you need to do — Claude Code stores the entry and will start the `remote-mcp` process automatically when it next launches.

**Heads-up — the command has two tokens you choose, and they happen to look the same in this tutorial.** Separating user-chosen tokens from fixed CLI syntax:

```
claude mcp add --scope user  remote-myserver  --  python -m remote_mcp --host  myserver
└── fixed Claude Code ──┘└─ you chose ──┘  ↑  └── fixed remote-mcp ──────┘└ you chose ┘
                                          separator
```

- The first **`remote-myserver`** is **the label Claude Code uses for this MCP server** — anything you'd like. It becomes the tool namespace the agent sees in the next step (`mcp__remote-myserver__Read`, etc.) and is also the name you'd later pass to `claude mcp remove`.
- The second **`myserver`** is the **`hosts:` key** you wrote in `config.yaml` in Step 2. It tells `remote-mcp` *which* remote to SSH into.

We picked matching names on purpose for this tutorial — it's the least confusing default. You could equally have written `claude mcp add --scope user prod-box -- python -m remote_mcp --host myserver`; the agent would see `mcp__prod-box__Read` operating on the same host.

---

## Step 5 — Restart Claude Code

Close Claude Code completely and reopen it. The MCP server list is loaded at startup — a running Claude Code session does not pick up newly-added servers.

After restart, verify the server is registered and healthy. Run from your shell:

```bash
claude mcp list
```

You should see an entry like:

```
remote-myserver: python -m remote_mcp --host myserver - ✓ Connected
```

The `✓ Connected` status means Claude Code successfully spawned the server and the MCP handshake completed. The 10 tools (`mcp__remote-myserver__Read`, `mcp__remote-myserver__Write`, ..., `mcp__remote-myserver__Feedback`) are now available to the agent in any Claude Code project.

If you see `✗ Failed to connect` instead, the server is registered but couldn't be spawned successfully — see the [Debug: MCP tools not appearing](../how-to/debug-mcp-not-appearing.md) guide.

---

## Step 6 — Your first remote tool call

Now we will ask Claude Code to use a remote tool. Open a new conversation and type exactly this:

```
Use the remote tools for myserver to read /etc/hostname on the remote host and tell me what it says.
```

Claude Code will call `mcp__remote-myserver__Read`. Watch the tool call appear in the conversation. The agent's tool call will look like:

```
mcp__remote-myserver__Read
  file_path: /etc/hostname
```

And the tool result returned to the agent will look like:

```
     1	your-host.example.com
```

The agent will then reply with something like:

```
The remote host's hostname is your-host.example.com.
```

The exact hostname will be whatever is in `/etc/hostname` on your server. If you see this exchange — the tool call, the numbered-line result, and the agent's reply — your first remote session is complete.

---

## What just happened

In six steps you:

1. Installed remote-mcp as a local Python package.
2. Told it which remote host to connect to.
3. Verified every tool works end-to-end over SSH.
4. Registered the server so Claude Code can spawn it.
5. Restarted so the tools loaded.
6. Watched the agent call a remote tool and read a real file.

The remote-mcp process runs locally, speaks MCP over stdio to Claude Code, and speaks SSH to your remote host. Claude Code does not know or care that the file is remote — it calls `Read` and gets numbered lines back, just like its native tools.

---

## Where to go next

**Get more from the tools.** Copy `CLAUDE.md.fragment.md` from this repo's root into the `CLAUDE.md` of your **local** project (the one Claude Code reads at startup — *not* a file on the remote host). It teaches the agent bandwidth-aware patterns — batching reads with MultiRead, using Grep with context lines instead of Grep-then-Read, running long builds in the background with `run_in_background`. Without it, the agent uses the tools correctly but not efficiently. For the three placement options (per-project, user-level, team-shared via git), see [Use the CLAUDE.md workflow fragment](../how-to/use-the-workflow-fragment.md).

**Understand the system.** Read the [Explanation: Architecture overview](../explanation/architecture.md) to get the mental model — what processes run, what protocols carry the data, and why the persistent bash session exists.

**Do more specific things.** The [How-to guides](../how-to/README.md) cover multi-host setups, ProxyJump through a bastion, tuning for slow networks, recovering from connection drops, and more.
