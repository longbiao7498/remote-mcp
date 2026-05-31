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
- Long-running operations (build / test / install / large downloads): **use `Bash(command="...", run_in_background=true, name="my-build", log_path="/home/user/my-build.log")`**. The agent isn't blocked.
  - v0.3.0 panel workflow:
    1. **Launch**: `Bash(run_in_background=True, name="X", log_path="/home/user/X.log", command="bash ~/X.sh")` — returns `id`, `pid`, `log_path`.
    2. **Query state**: `Jobs(name="X")` — observes remote liveness, updates state cache. Or `Jobs()` to list all.
    3. **Read log**: `Read("/home/user/X.log", offset=<last_line+1>)` — incremental poll, don't `Bash("cat log")`.
    4. **Kill**: `JobKill(name="X")` — default `kill -TERM -- -<pgid>`; or `JobKill(name="X", kill_cmd="scancel 12345")` for Slurm.
    5. **Archive when done**: once `Jobs(name="X")` shows `stopped` or `killed` and you've reviewed the log, call `JobArchive(name="X")` to free the name.
    6. **For failed kills**: after ≥ 3 failed `JobKill` attempts, give up via `JobArchive(name="X", as_zombie=True)`.
    7. **If panel disappears after CC restart**: `Bash("ls ~/.cache/remote-mcp-*-pid")` to find orphaned remote pids from old sessions.
  - Optionally attach a status script for rich single-call status: `JobScript(name="X", script="...", timeout=10)` — runs on every `Jobs(name="X")` call.
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

## remote-mcp v0.2.2 behavior (network failures)

- **`Error: SSH channel ... closed unexpectedly`**: the remote command's execution state is undetermined. Idempotent reads (`cat`, `ls`, `pwd`, `grep`) can be retried directly. Side-effect commands (`rm`, `mv`, `git push`, migrations) need to be verified first (use `Read` / `Bash("ls ...")`) before deciding to retry. Long tasks (`sleep`, training scripts) may still be running — check with `Bash("pgrep -af <command snippet>")`.

- **`Error: SSH connection ... reconnect failed`**: the network really is down. Wait a few seconds before issuing any further calls; or call `RemoteInfo` (does not use the network) as a cheap "are we back" probe before retrying the failed action.

- **`Error: Edit ... old_string not found`** combined with a recently-seen `[WARNING] SSH connection was lost`: the previous Edit may actually have succeeded — Edit / MultiEdit are explicitly not auto-retried (bug #1 from v0.2.2 spec). Read the file before deciding to re-Edit. If the file already shows the intended state, do NOT re-issue the Edit.

- **`[WARNING] ... snapshot ... missing AND re-upload failed`**: subsequent Bash calls will NOT load the user's PATH or aliases, and will start in `$HOME` rather than the configured cwd. Use absolute paths (e.g. `/home/user/miniconda3/bin/conda` instead of `conda`) and avoid relying on user aliases until the next MCP server restart.

- **Background task launch failure with response lost**: the tool automatically falls back to an SFTP read of the remote pid file. If both fail, the task is NOT added to the panel and an Error is returned with recovery instructions. If you suspect an orphan remote process, use:
  ```bash
  Bash("ls ~/.cache/remote-mcp-*-pid 2>/dev/null")
  Bash("for f in ~/.cache/remote-mcp-*-pid; do pid=$(cat $f); kill -0 $pid 2>/dev/null && echo \"$f: pid=$pid ALIVE\"; done")
  ```
