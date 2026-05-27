# Debug: MCP tools not appearing in Claude Code

> 中文版本：[debug-mcp-not-appearing.zh.md](./debug-mcp-not-appearing.zh.md)

## When to use this guide

You ran `claude mcp add` and restarted Claude Code, but none of the `mcp__remote-<host>__*` tools appear. This guide walks through the diagnostic steps in order of likelihood.

## What you need first

- The exact `claude mcp add` command you ran (to verify spelling)
- Terminal access to run diagnostic commands

## Steps

1. **Confirm the MCP server entry exists**

   ```bash
   claude mcp list
   ```

   Look for an entry like `remote-prod`. If it is missing, the `claude mcp add` command did not complete — re-run it:

   ```bash
   claude mcp add --global remote-prod -- python -m remote_mcp --host prod
   ```

   **If the entry IS present but you see different tool names than you expected** (e.g., `mcp__pixie-dust__Read` instead of `mcp__remote-prod__Read`), the **MCP server label** (the first argument to `claude mcp add`) doesn't match what you assumed. That label — distinct from the `--host` argument — determines the tool namespace. To rename, remove and re-add:

   ```bash
   claude mcp remove pixie-dust    # use the wrong-looking name from `claude mcp list`
   claude mcp add --global remote-prod -- python -m remote_mcp --host prod
   ```

   For the full disambiguation of these two names, see [Configure multiple remote hosts → step 2](./configure-multi-host.md#steps).

2. **Verify the server process starts without errors**

   The tool list is only populated if the MCP server process starts cleanly. Run it manually:

   ```bash
   python -m remote_mcp --host prod
   ```

   It should hang waiting for stdio input (Ctrl-C to exit). If it exits immediately with an error, the problem is in startup — fix the error before continuing.

   Common startup errors:

   | Error message | Cause | Fix |
   |---------------|-------|-----|
   | `No module named remote_mcp` | Wrong Python interpreter | Use `python -m pip install -e .` to align pip and python |
   | `Config file not found` | Missing or wrong config path | Create `~/.config/remote-mcp/config.yaml` |
   | `Host 'prod' not found in config` | Typo in `--host` or missing host key | Check config YAML key names match |
   | `FileNotFoundError: ... key_path` | Key file path wrong or missing | Verify `key_path` in config expands correctly |

3. **Test the SSH connection independently**

   ```bash
   python -m remote_mcp --host prod --test
   ```

   Expected: `Connected to prod (ubuntu@192.168.1.100). All tools: OK`

   If this fails, fix the SSH / config issue first. Tools cannot appear if the server cannot connect.

4. **Check which Python `claude mcp add` registered**

   Claude Code spawns the command exactly as registered. If you registered with `python` but the correct interpreter is `python3` or a virtualenv path, the process will fail silently.

   Verify by checking what `python` resolves to in your shell:

   ```bash
   which python
   python --version
   ```

   If needed, re-register with the full path:

   ```bash
   claude mcp remove remote-prod
   claude mcp add --global remote-prod -- /usr/bin/python3 -m remote_mcp --host prod
   ```

5. **Restart Claude Code completely**

   Tools are loaded at startup. A "restart" must be a full quit-and-relaunch, not just closing and reopening a tab. After launching, wait for the MCP servers to initialize (a few seconds) before checking for tools.

6. **Check Claude Code's MCP server logs**

   Claude Code writes MCP server stderr to a log file. Location varies by platform; on Linux:

   ```bash
   ls ~/.claude/logs/
   ```

   Look for a file named after your MCP server entry. Any Python traceback there points directly to the problem.

## Verification

After fixing the issue and restarting, confirm in Claude Code:

```
mcp__remote-prod__Bash("echo ok")
```

Should return `[host=prod cwd=/home/ubuntu]\nok`.

## When this doesn't work

- **Entry appears in `claude mcp list` but still no tools** — the process is registering but crashing before sending the tool list. Check Claude Code's MCP log file (step 6 above).
- **Tools appear but calls return errors** — the server is running but the SSH connection is failing. Re-run `python -m remote_mcp --host prod --test` to isolate the SSH problem.
- **Works in terminal but not in Claude Code** — Claude Code may use a different `PATH` or `HOME`. Register with absolute paths for both the interpreter and `--config` if needed.
