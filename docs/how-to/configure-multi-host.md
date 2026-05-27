# Configure multiple remote hosts

> 中文版本：[configure-multi-host.zh.md](./configure-multi-host.zh.md)

## When to use this guide

You need Claude Code to operate on two or three different servers in the same session. Each host gets its own MCP server entry and its own set of tools.

## What you need first

- remote-mcp installed (`pip install -e .`)
- SSH key-based access to each host
- Familiarity with the single-host setup (see the [tutorial](../tutorial/first-remote-session.md))

## Steps

1. **Add each host to `~/.config/remote-mcp/config.yaml`**

   ```yaml
   hosts:
     prod:
       hostname: 192.168.1.100
       user: ubuntu
       key_path: ~/.ssh/id_ed25519

     gpu:
       hostname: 10.0.0.60
       user: longbiao
       key_path: ~/.ssh/id_ed25519

     staging:
       hostname: 10.0.0.70
       user: ubuntu
       key_path: ~/.ssh/id_ed25519

   default_host: prod
   ```

   Each top-level key under `hosts:` becomes the host name you pass to `--host`.

2. **Register each host as a separate MCP server**

   ```bash
   claude mcp add --global remote-prod    -- python -m remote_mcp --host prod
   claude mcp add --global remote-gpu     -- python -m remote_mcp --host gpu
   claude mcp add --global remote-staging -- python -m remote_mcp --host staging
   ```

   **Each line has two tokens you choose and a lot of fixed CLI syntax.** Separating them:

   ```
   claude mcp add --global  <NAMESPACE>  --  python -m remote_mcp --host  <HOST-KEY>
   └── fixed Claude Code ──┘└─ you ──┘   ↑   └── fixed remote-mcp ──────┘└─ you ──┘
                            choose      separator                         choose
   ```

   - **`<NAMESPACE>`** — Claude Code's label for this MCP server. It becomes the **tool prefix** the agent sees: `mcp__<NAMESPACE>__Read`, etc. Also the name you'd use with `claude mcp remove <NAMESPACE>` or `claude mcp list`.
   - **`<HOST-KEY>`** — the key under `hosts:` in `config.yaml` from step 1. Picks which remote to SSH into.

   Everything else (`claude mcp add`, `--global`, `--`, `python -m remote_mcp`, `--host`) is **fixed CLI syntax** — type it verbatim.

   The two tokens you choose are independent. You *could* write `claude mcp add --global pixie-dust -- python -m remote_mcp --host prod` and the agent would see `mcp__pixie-dust__Read` operating on the `prod` host. **The matching `remote-<HOST-KEY>` convention above is the recommended default** — when you see `mcp__remote-prod__Bash` in a tool call, it's obvious which remote it operates on. Stick to it unless you have a reason not to.

3. **Restart Claude Code**

   The tool list is loaded at startup. After restart, you will see:

   ```
   mcp__remote-prod__Read     mcp__remote-prod__Bash     ...
   mcp__remote-gpu__Read      mcp__remote-gpu__Bash      ...
   mcp__remote-staging__Read  mcp__remote-staging__Bash  ...
   ```

4. **Smoke-test each host before starting work**

   ```bash
   python -m remote_mcp --host prod    --test
   python -m remote_mcp --host gpu     --test
   python -m remote_mcp --host staging --test
   ```

   Expected output for each: `Connected to <host> (<user>@<hostname>). All tools: OK`

## Verification

In Claude Code, ask the agent to run:

```
mcp__remote-prod__Bash("hostname")
mcp__remote-gpu__Bash("hostname")
```

Each result begins with `[host=prod cwd=...]` or `[host=gpu cwd=...]`. Confirm the hostnames match.

## When this doesn't work

- **Tools don't appear after restart** — see [Debug: MCP tools not appearing](./debug-mcp-not-appearing.md).
- **One host connects but another doesn't** — run `python -m remote_mcp --host <name> --test` for the failing host and fix the SSH error before re-registering.
- **Host behind a bastion** — see [Set up ProxyJump](./set-up-proxyjump.md) before adding the host entry.
