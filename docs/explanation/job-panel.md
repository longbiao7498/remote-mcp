# Job Panel: Design Rationale

> 中文版本：[job-panel.zh.md](./job-panel.zh.md)

This document explains the design decisions behind the v0.3.0 background task panel — why the architecture is structured the way it is, what alternatives were rejected, and what consequences follow from each choice. Read it before modifying the panel subsystem.

For the normative specification, see [`docs/superpowers/specs/2026-05-31-v0.3.0-job-panel.md`](../superpowers/specs/2026-05-31-v0.3.0-job-panel.md) (§4, §7, §10, §11).

## Why local-first metadata

Panel metadata (`<id>-meta.json`) and status script sources (`<id>-status.sh`) live on the MCP host — the same machine running Claude Code — not on the remote. Remote files are limited to three categories: the pid file, the status.sh cache, and the log.

**The reason is latency.** The MCP server is a long-lived process; every tool call that needs to "check the panel" could touch the panel many times per session. If panel queries required a remote SSH round-trip to read state, that round-trip (typically 20–200 ms on academic clusters) would be charged on every `Jobs()`, every `JobKill`, every `JobArchive`. On a high-latency link with 10 panel tasks, list-mode would need 10 parallel stat calls or a compound bash pipeline — all avoidable.

Local file IO is essentially free. The tradeoff is that the metadata does not survive MCP host reboot or process migration; this is accepted because the panel's lifecycle is explicitly tied to the Claude Code session.

A second benefit: **JobArchive is purely local**. Since the authoritative state lives locally, archiving a task is a `mv` of a JSON file plus an optional `mv` of a shell script. No SSH connection needed, no "what if the remote is down when I archive" edge case.

## Why id-based directory naming (not name-based)

Each task gets a monotonically increasing integer `id`, not a directory named after its alias. The alias (`name`) is a field inside `<id>-meta.json`.

**This allows safe name reuse after archive**. A typical long-running workflow cycles through many builds with the same name ("python-build", "train-run-1", etc.). If the directory were named after the alias, archiving would require renaming the directory and invalidating any existing references. With id-based naming, archiving is just `mv 17-meta.json archive/17-meta.json` — the name is released in the active namespace immediately, and the old task remains queryable via `Jobs(id=17)` from its new location in `archive/`.

The `archive/` and `zombie/` subdirectories are flat (no further nesting), which makes directory listing trivial and avoids the "how deep to recurse" question.

## Why JobArchive is purely local

`JobArchive` reads the cached `state` from `meta.json` and performs only local file operations. It never issues `kill -0` to verify whether the remote process is truly dead before accepting the archive.

This is intentional — and the reasoning flows from the **state cache design** (§7.1 of the spec):

1. `stopped` and `killed` are **terminal states**. Once a process is dead, it stays dead. PID reuse could theoretically make a new process inherit the old PID, but the panel's kill-observation machinery skips terminal-state tasks (it does not call `kill -0` again once stopped/killed is cached), preventing false-positive liveness readings.
2. Because terminal states are reliable once cached, `JobArchive` on a `stopped` or `killed` task is safe without a remote check.
3. If the cached state is still `running` or `kill_failed`, `JobArchive` rejects with an error — not as a "safety net to prevent archiving a live process" but as a **semantic guard**: if the cached state says running, the agent hasn't confirmed the task finished and hasn't read its results. Archiving without review is the wrong action.

The correct agent flow is: `Jobs(name=X)` to refresh state → `Read(log_path)` to review results → `JobArchive(name=X)` to archive. This flow works correctly whether the cached state is stale or current, because:
- If stale-running but actually stopped: `Jobs` refreshes to stopped; `Read` shows the completed output; `JobArchive` succeeds.
- If truly running: `Jobs` confirms running; the agent knows to wait.

## How state caching works

The state field in `meta.json` is the panel's primary performance lever. It allows `Jobs()` list mode to issue **at most one batched remote exec** regardless of how many tasks are in the panel, by skipping `kill -0` for terminal-state tasks.

The caching lifecycle:
1. **At launch**: `state` is pre-set to `"running"` before the remote process is confirmed (because launching = running by definition). `pid` is backfilled after confirmation.
2. **After each `Jobs` or `JobKill` observation**: the derived state is written back to `meta.json`. Subsequent tool calls see the fresh value without a remote op.
3. **Terminal states are sticky**: once `stopped` or `killed` is written, `Jobs` list mode never re-observes that task's pid. The `kill_attempts` list on `meta.json` carries the chronology of JobKill attempts, enabling `Jobs(id=N)` to reconstruct history without remote access.

The tradeoff: if the MCP server crashes and restarts between a `Jobs` call and a `JobKill`, the cached state may lag by one cycle. This is acceptable — the next `Jobs` call corrects it, and tools that need fresh state (`JobKill`) always issue their own `kill -0` as part of the packed exec.

## The "Archive = processed results" semantics

The most non-obvious design choice in JobArchive is that it refuses to archive `running` tasks — not because it is trying to prevent live-process cleanup, but because archive means "I have finished processing this task's outputs."

Consider the agent's mental model:
- If state = running in the cache, the agent (by definition) last observed the task as running. The agent cannot have reviewed the outputs of a task it still believes to be running.
- Archiving without reviewing outputs is a data loss pattern — you'd move the meta away and lose easy access to `log_path`, `kill_attempts`, `status_script_output`, etc.

By blocking `JobArchive` when `state ∈ {running, kill_failed}`, the tool enforces the correct flow. The `running` guard forces the agent to call `Jobs` first (which will either confirm still-running or update to stopped/killed) and then `Read` the log.

## The zombie escape hatch

When `JobKill` has been attempted multiple times (threshold: 3) and the process refuses to die, the agent has two options:
1. Continue trying with different signals or runtime-specific commands (e.g., `scancel`, SIGKILL).
2. Give up: `JobArchive(name=X, as_zombie=True)`.

`as_zombie=True` acknowledges "I give up; the process keeps running on remote outside panel management." The task is moved to `zombie/` with `zombie=true` in its meta. The name is released for reuse.

The zombie directory is separate from `archive/` for a practical reason: `Jobs(filter='zombies')` and the zombie count threshold check need to enumerate zombies cheaply — `len(os.listdir("zombie/"))` is O(1), while scanning `archive/` and filtering `zombie==true` is O(N).

The escalation warning at ≥ 5 zombies is a signal to the agent (and ultimately the user) that something systemic is wrong — either the kill strategy is consistently wrong, or the remote host has a structural issue (D-state processes, root-owned processes, kernel bugs). The warning fires once per `JobArchive(as_zombie=True)` call that crosses the threshold, not on every subsequent tool call, to avoid noise.

## Session ID (sid) and panel persistence

The `sid` is derived from `PPID + parent process create_time + hostname` via `psutil`. This choice has a specific property: if the MCP server crashes and is restarted by Claude Code (which is the MCP host process's parent), the new MCP server sees the same PPID and the same parent start_time — so the derived `sid` is identical, and the panel directory is preserved.

This covers the most common "panel loss" scenario (MCP server crash or restart during a long session) without requiring any coordination between Claude Code and the MCP server.

The case that cannot be handled: the user closes Claude Code entirely and reopens it (or uses `claude -c` to resume a session). The new Claude Code process has a new PID, so the MCP server's PPID changes, so the `sid` changes, and the old panel directory becomes invisible to panel tools. The remote tasks are still running; the local meta files still exist under the old `sid` directory. The recovery path is via `Bash("ls ~/.cache/remote-mcp-*-pid")` which enumerates all sid-namespaced pid files across all sessions.

This is an accepted limitation of the v0.3.0 design. Future work could address it if Claude Code exposes a stable session identifier via the MCP initialization handshake.

## exec_with_snapshot helper extraction

The `exec_with_snapshot(conn, command, timeout) -> ExecResult` helper was extracted from `_bash_foreground` to give panel tools access to the same snapshot-aware exec infrastructure without duplicating the timeout loop, partial-stdout collection, and `</dev/null` stdin setup.

All panel tools that run remote commands (`Jobs` observation, `JobKill` packed exec, `JobScript` first-run, `JobScript` upload-and-exec) go through this helper. This ensures consistent behavior across: `op_timeout_default` channel timeout, `\r\n` normalization, partial output collection on channel death, and the snapshot `source` preamble.

## Known limitation: panel does not survive Claude Code restart

As described under Session ID, restarting Claude Code produces a new `sid` and a new panel directory. This is the expected behavior for v0.3.0. Agents relying on long-running tasks across CC sessions should note the recovery workflow:

```bash
# On new session: find orphaned remote tasks from old sessions
Bash("ls ~/.cache/remote-mcp-*-pid 2>/dev/null")

# Check which are alive
Bash("for f in ~/.cache/remote-mcp-*-pid; do pid=$(cat $f); kill -0 $pid 2>/dev/null && echo \"$f: pid=$pid ALIVE\"; done")
```

From the old pid file names, the `<sid>` and `<id>` can be recovered to locate the corresponding `~/.local/share/remote-mcp/jobpane/<old_sid>/` directories on the MCP host.

## See also

- Reference: [Jobs](../reference/tools/jobs.md), [JobKill](../reference/tools/job-kill.md), [JobArchive](../reference/tools/job-archive.md), [JobScript](../reference/tools/job-script.md), [Bash](../reference/tools/bash.md)
- Spec §4 (architecture), §7 (state machine), §10 (JobKill dual-tier warnings), §11 (JobArchive zombie semantics)
