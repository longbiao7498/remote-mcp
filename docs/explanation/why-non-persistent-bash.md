# Why non-persistent Bash

> 中文版本：[why-non-persistent-bash.zh.md](./why-non-persistent-bash.zh.md)

> See also: [the v0.2.0 spec](../../superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md), authoritative.

In v0.1.x, the Bash tool kept a single bash process alive through a persistent SSH channel. `cd`, `export`, `source venv/bin/activate` survived across tool calls. This matched what an interactive human user would expect from a terminal.

In v0.2.0 we removed that. Each Bash call now spawns a fresh shell, runs the command, and exits. State does NOT persist.

## Why we changed

**Alignment with Claude Code native.** Direct testing showed Claude Code's native Bash tool resets cwd and env between calls. Agents trained on CC behavior assume non-persistence. Our persistent model was an unintended deviation — agents would `cd` once and assume they're still there, then get confused when relative paths failed (or worse, succeeded against the wrong file).

**A class of compounding bugs.** Persistent bash with a PTY caused `srun`, `cat` (no args), and other stdin-reading commands to hang forever — the persistent PTY meant our stdin watcher never closed and the remote command never saw EOF. The fix was `</dev/null` on every command, but combined with persistence this created subtle interactions (stdin redirected per command but the PTY itself persistent → behavior diverged from agents' mental model).

**Mechanical complexity.** Supporting persistent bash required: sentinel protocol to mark command boundaries on a continuous stdout stream, a reader thread to prevent paramiko buffer deadlock, PTY allocation for SIGINT delivery via Ctrl-C, `setsid` wrappers for background commands, and a fragile init sequence (`set +m`, `stty -echo`, `exec 2>&1`, ...). About 350 LOC of supporting machinery. Non-persistent is ~50 LOC with no edge cases.

## What we kept

The convenience of "shell environment is loaded once, not per call". We snapshot the bashrc-loaded environment (via `bash -ic 'declare -p; declare -fp; alias'`) at SSH connect time, and each Bash call `source`s the snapshot before running the user's command. PATH, aliases, conda init, `module load` — all preserved. This is the same trick Claude Code native uses (`/home/lb/.claude/shell-snapshots/snapshot-bash-*.sh`).

## What agents adapt to

`cd dir && cmd` instead of `cd dir` then `cmd`. `FOO=bar cmd` instead of `export FOO=bar` then `cmd`. `venv/bin/python script.py` instead of `source venv/bin/activate` then `python script.py`. All are normal CC native patterns.

If a workflow truly cannot work non-persistently (ssh-agent chains, complex stateful REPLs), a future `mode: persistent` opt-in is on the roadmap (see spec §15.2).
