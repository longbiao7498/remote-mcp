> 中文版本：[CLAUDE.md.fragment.zh.md](./CLAUDE.md.fragment.zh.md)

## remote-mcp v0.2.0 behavior (shell + paths)

- **Bash is non-persistent**: `cd dir`, `export FOO=bar`, `source venv/bin/activate` do NOT survive across calls. Chain inline: `cd dir && cmd`, `FOO=bar cmd`, `venv/bin/python script.py`.
- **Paths can be relative**: all file/search tools accept paths relative to the configured `cwd` (`--cwd /opt/app`). `Read("config.yaml")` reads `/opt/app/config.yaml`. `~` in tool args is NOT allowed — use absolute or relative-to-cwd. The current cwd appears in every tool's output as `[host=X cwd=Y]`.
- **Glob/Grep output**: absolute paths (e.g. `/opt/app/foo.py`) — feed directly to Read/Edit without manipulation.

## Working on a remote host (remote-mcp tool usage guide)

This project operates a remote server through `mcp__remote-<host>__*` tools. The SSH link is bandwidth-limited and high-latency. Follow these workflows:

### Single-host mode

**Exploring code / reading the repo**
- To find code, use Grep first to locate the keyword. If you need context, **use Grep's `context=5` (or `before`/`after`) to get the match plus surrounding code in one round-trip** — don't Grep then follow up with Read.
- Just want to know whether a file exists, how big it is, or when it was modified? **Use FileStat** — don't probe with Read (you might transfer 50 MB just to find out the file shouldn't have been read).
- Exploring several related files (e.g. config / models / utils as a group)? **Make one MultiRead call**, not consecutive Read calls.

**Editing files**
- Multiple edits to the same file? **Always use MultiEdit**. Don't chain consecutive Edit calls.

**Shell operations**
- **Shell state does not persist across calls.** Each Bash invocation is a fresh shell starting at the configured cwd. `cd`, `export`, `source venv/bin/activate` only take effect within that single call.
- For multi-step operations that need shared state, chain commands in one call: `cd dir && cmd1 && cmd2`. To activate a venv and run a command: `venv/bin/python script.py` or `. venv/bin/activate && python script.py` — all in one Bash call.
- For more complex logic, write a script (Write to upload → Bash to execute).
- Long-running operations (build / test / install / large downloads): **use `Bash(command="...", run_in_background=true)`**. The agent isn't blocked.
  - The tool's return prints the PID, log path, and 4 ready-to-paste command templates — **just copy them**.
  - Use `Read(log_path, offset=<last_line+1>)` to incrementally pull the log. Don't use `Bash("cat log")`.
  - When the task is done (or you've decided to abandon it), **always `Bash("kill -TERM -- -<pid>")` to clean up**.
- For foreground Bash long operations, set a large explicit timeout (e.g. 600s); if it might take more than a few minutes, just use `run_in_background`.
- Be careful with high-output commands: `find /`, `ls -R /`, `grep -r common-word /` will flood the bandwidth — think before you run.
- For file transfers (binary or large): **prefer `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** over the `Upload` / `Download` tools. scp/rsync are non-blocking when launched in background and support any file size. The `Upload`/`Download` tools are a Windows fallback for users without scp in PATH, and they're capped at `transfer_size_cap` (default 100 MB). On Linux/macOS, scp wins on every axis.

### Multi-host mode (2-3 hosts at once)

- Tool call results end with a `[host=X cwd=Y]` suffix. Pay attention to which host you're operating on.
- Try to concentrate work on a single host; cross-host coordination raises the error rate.
- Cross-host file transfer: use Bash with `scp <local>:<path> <remote>:<path>` (requires the user to have pre-arranged SSH trust between hosts). **Don't** use the Read-via-local-then-Write "double hop" pattern — it doubles the bandwidth cost.
- When you see `[WARNING] SSH connection to <host> was lost`, only that host's state is lost — other hosts are unaffected.

### Continuous improvement feedback

remote-mcp ships a `Feedback` tool that lets you (the agent) record issues you hit or ideas you have during the work. The maintainer reads these to iterate.

✅ **DO**:
- A remote-mcp tool behaved differently from Claude Code's native equivalent (schema mismatch, error wording drift, output corruption)
- A tool has a bug: unexpected timeout, output corruption, behavior at odds with the docs
- You thought "if there were an X tool, or Y parameter on Z, this would be much simpler" — and you can describe it concretely enough to specify an API
- Workflow friction: a common scenario takes 3+ tool calls when it should take 1

❌ **DON'T**:
- Bugs in the user's code (fix the user's code instead)
- Remote system problems (these belong in ops records)
- Speculation not grounded in something you actually encountered

**Calling convention**:
- `category="bug"` paired with actual reproduction steps
- `category="enhancement"` paired with enough detail to mock the API
- **Don't interrupt the current task** — file the feedback and continue
- Summary in one line; details for context

**Privacy**: Writes to local `~/.local/share/remote-mcp/feedback.jsonl`. Not transmitted anywhere.
