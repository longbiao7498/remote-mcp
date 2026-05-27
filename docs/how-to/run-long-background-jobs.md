# Run long-running background jobs

> 中文版本：[run-long-background-jobs.zh.md](./run-long-background-jobs.zh.md)

## When to use this guide

You need to start a build, test suite, package install, or data pipeline that will run for minutes — and you do not want the agent to block waiting for it. Use `run_in_background=true` on the `Bash` tool.

## What you need first

- A working host connection (run `python -m remote_mcp --host <name> --test`)
- The command you want to run (it must be non-interactive — no prompts, no TTY)

## Steps

1. **Start the job in the background**

   Call `Bash` with `run_in_background=true`. The tool returns immediately with a PID and a log path:

   ```
   Bash("make -j4 all", run_in_background=true)
   ```

   Response:

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

   Copy the PID and log path exactly as shown — do not guess them.

2. **Check whether the job is still running**

   Before reading output, always verify the PID is still live. PID reuse is rare but possible if the process has already exited:

   ```
   Bash("kill -0 12345 && echo running || echo done")
   ```

   `running` means the process group is alive. `done` means it has exited (log file still exists for inspection).

3. **Read new output incrementally**

   Use `Read` with `offset=` to fetch only new lines since the last read. Track the last line number you received:

   ```
   Read("/tmp/rmcp-bg-abc123def456.log", offset=1)
   ```

   On the next poll, pass `offset=<number of lines read so far + 1>` to avoid re-reading old output. Do not use `Bash("cat /tmp/rmcp-bg-abc123def456.log")` — it retransfers the whole file on every poll.

4. **Stop the job if needed**

   The command uses the process group ID (PGID = PID when started with `setsid`) to kill all child processes:

   - Graceful (SIGTERM, lets the process clean up):
     ```
     Bash("kill -TERM -- -12345")
     ```
   - Forced (SIGKILL, immediate):
     ```
     Bash("kill -KILL -- -12345")
     ```

   Always prefer SIGTERM first, then wait a moment and use SIGKILL only if the process did not exit.

5. **Clean up the log file when done**

   Log files in `/tmp/rmcp-bg-*.log` are intentionally left for post-mortem. Remove them when you are finished:

   ```
   Bash("rm /tmp/rmcp-bg-abc123def456.log")
   ```

   Or remove all background logs at once:

   ```
   Bash("rm -f /tmp/rmcp-bg-*.log")
   ```

## Verification

After starting the job:

```
Bash("kill -0 12345 && echo running || echo done")
```

Should return `running` within a few seconds. After the job completes, the same command returns `done` and `Read` on the log path shows the full output including the final exit status (if you appended `; echo "Exit: $?"` to your original command).

## When this doesn't work

- **`Error: failed to launch background task`** — the remote host may lack `setsid` or `nohup`. Verify: `Bash("which setsid nohup")`. If missing, install them (`apt install util-linux`).
- **`kill -0 <pid>` returns `done` immediately** — the command exited at startup. Read the log file for the error message. Common cause: the command path is wrong or a required environment variable is missing (the background environment starts fresh — re-export anything your command needs, or set it inline: `Bash("MY_VAR=value make all", run_in_background=true)`).
- **Log file grows without bound** — add `| head -10000` to your command or redirect only what you need. `/tmp` is cleaned at reboot; for long-running daemons, redirect to a persistent path.
