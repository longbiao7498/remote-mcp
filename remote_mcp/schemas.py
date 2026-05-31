"""JSON schemas for all 13 tools. See spec §6."""

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "Absolute path to the file on the remote server"},
        "offset": {"type": "integer", "description": "Start line number (1-based). Default: 1", "default": 1},
        "limit": {"type": "integer", "description": "Max lines to read. Default: 2000", "default": 2000},
    },
    "required": ["file_path"],
}

WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["file_path", "content"],
}

EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "old_string": {"type": "string"},
        "new_string": {"type": "string"},
        "replace_all": {"type": "boolean", "default": False},
    },
    "required": ["file_path", "old_string", "new_string"],
}

MULTIEDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean", "default": False},
                },
                "required": ["old_string", "new_string"],
            },
        },
    },
    "required": ["file_path", "edits"],
}

MULTIREAD_SCHEMA = {
    "type": "object",
    "properties": {
        "reads": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "offset": {"type": "integer", "default": 1},
                    "limit": {"type": "integer", "default": 2000},
                },
                "required": ["file_path"],
            },
        },
    },
    "required": ["reads"],
}

FILESTAT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_paths": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
    },
    "required": ["file_paths"],
}

BASH_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "description": {
            "type": "string",
            "default": "",
            "description": "Brief description of the command (CC native compat). When run_in_background=true, this is also stored as the task description in the panel (max 500 chars; longer is truncated with a notice in the return).",
        },
        "timeout": {"type": "number", "default": 120},
        "run_in_background": {"type": "boolean", "default": False},
        "log_path": {
            "type": "string",
            "description": "Optional. Absolute remote path for stdout+stderr redirection (background only). Defaults to ~/.cache/remote-mcp-<sid>-<id>.log (alongside pid file; persists across reboots unlike /tmp). Parent dirs auto-created via remote mkdir -p (one Bash exec). If a non-directory file exists at the parent path, Error returned and task not launched. If the target log file exists, it is overwritten (shell '>' semantics).",
        },
        "name": {
            "type": "string",
            "description": "Optional. Job alias for panel reference (background only). Defaults to 'bg-<uuid12>'. Must be unique among active (non-archived) jobs in the current session+host — collision returns Error. Pattern: [A-Za-z0-9_.-]+ length 1-64.",
        },
    },
    "required": ["command"],
}

GLOB_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string"},
        "path": {"type": "string", "default": "."},
    },
    "required": ["pattern"],
}

GREP_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string"},
        "path": {"type": "string"},
        "include": {"type": "string", "default": ""},
        "case_insensitive": {"type": "boolean", "default": False},
        "before": {"type": "integer", "default": 0},
        "after": {"type": "integer", "default": 0},
        "context": {"type": "integer", "default": 0},
        "head_limit": {"type": "integer", "default": 200},
        "output_mode": {
            "type": "string",
            "enum": ["content", "files_with_matches", "count"],
            "default": "content",
        },
    },
    "required": ["pattern", "path"],
}

FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["bug", "enhancement"]},
        "summary": {"type": "string"},
        "details": {"type": "string", "default": ""},
    },
    "required": ["category", "summary"],
}

UPLOAD_SCHEMA = {
    "type": "object",
    "properties": {
        "local_path": {"type": "string", "description": "Absolute path on the LOCAL machine (where the MCP server runs). ~ is expanded."},
        "remote_path": {"type": "string", "description": "Absolute path on the remote host. Overwrites if exists. Parent dirs auto-created via SFTP mkdir."},
    },
    "required": ["local_path", "remote_path"],
}

DOWNLOAD_SCHEMA = {
    "type": "object",
    "properties": {
        "remote_path": {"type": "string", "description": "Absolute path on the remote host."},
        "local_path": {"type": "string", "description": "Absolute path on the LOCAL machine. ~ is expanded. Parent directory must already exist (not auto-created)."},
    },
    "required": ["remote_path", "local_path"],
}

REMOTEINFO_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

ALL_TOOL_SCHEMAS = {
    "Read": READ_SCHEMA,
    "Write": WRITE_SCHEMA,
    "Edit": EDIT_SCHEMA,
    "MultiEdit": MULTIEDIT_SCHEMA,
    "MultiRead": MULTIREAD_SCHEMA,
    "FileStat": FILESTAT_SCHEMA,
    "Bash": BASH_SCHEMA,
    "Glob": GLOB_SCHEMA,
    "Grep": GREP_SCHEMA,
    "Feedback": FEEDBACK_SCHEMA,
    "Upload": UPLOAD_SCHEMA,
    "Download": DOWNLOAD_SCHEMA,
    "RemoteInfo": REMOTEINFO_SCHEMA,
}


# Tool descriptions (M1 — bandwidth-aware hints embedded). See spec §10.1.
READ_DESC = (
    "Read a file on the remote server. Returns lines with `     <lineno>\\t<line>` prefix. "
    "Transfers file content over SSH. To check existence/size only, use FileStat. "
    "To search for specific text, use Grep with -A/-B/-C for context. "
    "To read multiple related files at once, use MultiRead."
)
WRITE_DESC = (
    "Write content to a file on the remote server (overwrites existing). "
    "Bytes are transferred over SSH. Compose the full file content locally before calling, not incrementally."
)
EDIT_DESC = (
    "Edit a file by replacing an exact string. Requires old_string to appear exactly once unless replace_all=true. "
    "Reads and writes the full file over SSH. For multiple changes to the same file, use MultiEdit in a single call."
)
MULTIEDIT_DESC = (
    "Apply multiple edits to a single file atomically. "
    "Reads and writes the file once for any number of edits. "
    "Always prefer this over multiple Edit calls on the same file."
)
MULTIREAD_DESC = (
    "Batch reads multiple files in one network round-trip. "
    "Always prefer this over consecutive Read calls when inspecting 2+ files."
)
FILESTAT_DESC = (
    "Returns metadata (existence, size, mtime, mode) without transferring file content. "
    "Use this before Read to avoid accidentally downloading huge files. Accepts a path or a list of paths."
)
BASH_DESC = (
    "Execute a shell command on the remote server.\n"
    "\n"
    "Shell state (cwd, env vars, sourced venvs) does NOT persist across calls — "
    "each invocation is a fresh `bash --noprofile --norc` process. The configured "
    "cwd and a snapshot of env/aliases/functions (captured once at MCP startup) "
    "are sourced before your command runs. Chain state inline: `cd dir && cmd`, "
    "`VAR=v cmd`, `venv/bin/python script.py`.\n"
    "\n"
    "Foreground (default) actual wrap:\n"
    "  bash --noprofile --norc -c '<your command>' </dev/null\n"
    "The `</dev/null` makes stdin-reading commands (cat, srun, python REPL) "
    "return immediately instead of hanging.\n"
    "\n"
    "Background (run_in_background=true) actual wrap:\n"
    "  ( setsid nohup bash --noprofile --norc -c '<your command>' \\\n"
    "    > <log_path> 2>&1 </dev/null & \\\n"
    "    echo $! > ~/.cache/remote-mcp-<sid>-<id>-pid; echo BG_PID=$! )\n"
    "setsid + nohup + </dev/null + & together guarantee survival across SSH "
    "disconnects and shell exits — you do NOT need to write nohup/disown yourself.\n"
    "\n"
    "Background returns structured fields: id, name, log_path, pid, started_at. "
    "Optional params for background:\n"
    "  log_path: absolute remote path for stdout/stderr (default "
    "~/.cache/remote-mcp-<sid>-<id>.log; persists across reboots). Parent dirs "
    "auto-created; conflict with existing non-directory file → Error.\n"
    "  name: panel alias (default bg-<uuid12>). Must be unique among active jobs "
    "in this session+host; collision → Error.\n"
    "  description: panel task description (also CC native compat; max 500 chars).\n"
    "\n"
    "Manage background tasks with the panel tools — do NOT hand-roll pgrep/kill:\n"
    "  Jobs() / Jobs(id=N) / Jobs(filter='stopped_unprocessed'|'stuck_kill'|'zombies')\n"
    "  JobKill(name=X[, kill_cmd=...])\n"
    "  JobArchive(name=X[, as_zombie=True])\n"
    "  JobScript(name=X, script='...', timeout=N)\n"
    "Archive is for tasks you have processed the results of. Typical flow:\n"
    "Bash(run_in_background=True, ...) → wait → Jobs(name=X) (refresh state)\n"
    "→ Read(log_path) (review output) → JobArchive(name=X). Archive rejects\n"
    "running/kill_failed tasks; that's not stale-cache defense — it's a\n"
    "reminder that you haven't processed the results yet.\n"
    "\n"
    "Background panel does NOT survive Claude Code restart (PPID changes →\n"
    "new sid → old panel orphaned but tasks keep running). To recover old\n"
    "tasks after CC restart, ls ~/.cache/remote-mcp-*-pid on remote.\n"
    "\n"
    "Batching tips for foreground: chain related commands with '&&'; pipe large "
    "outputs through head/tail to stay under bash_output_cap (default 100KB)."
)
GLOB_DESC = (
    "Find files matching a glob pattern (server-side). "
    "Output is capped — narrow the path argument when searching large trees."
)
GREP_DESC = (
    "Search file contents for a regex pattern. Filters server-side and returns only matching lines. "
    "Use context/before/after to include surrounding lines in the same call instead of following up with Read. "
    "Use output_mode='files_with_matches' or 'count' when you don't need the matched lines themselves."
)
FEEDBACK_DESC = (
    "Record a bug or enhancement idea about the remote-mcp tools themselves (NOT about the user's code or remote system). "
    "Use 'bug' when a remote-mcp tool behaves wrong; 'enhancement' for tool improvements you imagine while working. "
    "Brief, non-blocking — file and continue your task."
)
UPLOAD_DESC = (
    "Push a local file to the remote via SFTP. Binary-safe. "
    "On Linux/macOS, PREFER `Bash(\"scp <local> <user>@<host>:<remote>\", run_in_background=true)` instead — "
    "it's non-blocking, handles any size, and supports resume with rsync. "
    "This tool is primarily for Windows users without scp in PATH. "
    "Max file size: transfer_size_cap (default 100 MB); larger files return an Error "
    "with a ready-to-paste scp command."
)

DOWNLOAD_DESC = (
    "Pull a remote file to local via SFTP. Binary-safe. "
    "On Linux/macOS, PREFER `Bash(\"scp <user>@<host>:<remote> <local>\", run_in_background=true)` — "
    "non-blocking, any size, resumable. "
    "This tool is primarily for Windows users without scp. "
    "Max file size: transfer_size_cap (default 100 MB); larger returns an Error "
    "with a ready-to-paste scp command."
)

REMOTEINFO_DESC = (
    "Return the connection's CONFIGURED identity: host label, user, hostname, "
    "port, jump_host. No SSH call is made — values come from "
    "~/.config/remote-mcp/config.yaml. VPN-safe: in VPN scenarios the IP "
    "the remote reports via `hostname -I` differs from the IP the client "
    "uses to reach it; this tool returns the latter."
)

ALL_TOOL_DESCRIPTIONS = {
    "Read": READ_DESC, "Write": WRITE_DESC, "Edit": EDIT_DESC,
    "MultiEdit": MULTIEDIT_DESC, "MultiRead": MULTIREAD_DESC,
    "FileStat": FILESTAT_DESC, "Bash": BASH_DESC, "Glob": GLOB_DESC,
    "Grep": GREP_DESC, "Feedback": FEEDBACK_DESC,
    "Upload": UPLOAD_DESC,
    "Download": DOWNLOAD_DESC,
    "RemoteInfo": REMOTEINFO_DESC,
}

JOBS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Job name to query (single-task mode). Mutually exclusive with id.",
        },
        "id": {
            "type": "integer",
            "description": "Job id to query (single-task mode). Mutually exclusive with name.",
        },
        "filter": {
            "type": "string",
            "enum": ["stopped_unprocessed", "stuck_kill", "zombies"],
            "description": (
                "List-mode filter. stopped_unprocessed: state ∈ {stopped, killed} and not archived "
                "(agent's cron-poll target for tasks that finished). "
                "stuck_kill: state == kill_failed AND kill_attempts >= 3 AND not archived "
                "(tasks resisting your kill — review attempts and decide on JobArchive(as_zombie=True)). "
                "zombies: archived with zombie=true (tasks you gave up on; processes may still be "
                "running on remote outside panel management)."
            ),
        },
    },
}

JOBS_DESC = (
    "Query the background task panel. Two modes:\n"
    "- List mode (no name/id): Jobs() lists all active tasks. Optional "
    "filter='stopped_unprocessed'|'stuck_kill'|'zombies'.\n"
    "- Single mode: Jobs(name=X) or Jobs(id=N) returns full detail including "
    "command, kill_attempts, archived_at, and (if attached) status_script_output.\n"
    "Jobs updates the cached state in panel metadata as a side effect — always "
    "call Jobs before JobArchive to ensure the cache reflects the current observation. "
    "Retries are safe (state writeback is idempotent)."
)

ALL_TOOL_SCHEMAS["Jobs"] = JOBS_SCHEMA
ALL_TOOL_DESCRIPTIONS["Jobs"] = JOBS_DESC

JOBSCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "id": {"type": "integer"},
        "script": {"type": "string", "description": "Bash script body. Stored locally + uploaded to remote cache (auto-reuploaded if missing). Pass empty string '' to clear (deletes local source only)."},
        "timeout": {"type": "integer", "description": "Required. Seconds. Pick based on what your script does (simple pgrep+tail=5; large log=30; calling external services=60). Stored as script_timeout in meta; reused on every Jobs(name=X) call."},
    },
    "required": ["script", "timeout"],
}
JOBSCRIPT_DESC = (
    "Attach a status script to a job. The script runs server-side on each "
    "Jobs(name=X) single-task query and the output appears in "
    "status_script_output. Source is stored locally; remote cache is "
    "auto-managed. Pass script='' to clear. timeout is required — pick "
    "based on what your script does (5-60 seconds typical)."
)
ALL_TOOL_SCHEMAS["JobScript"] = JOBSCRIPT_SCHEMA
ALL_TOOL_DESCRIPTIONS["JobScript"] = JOBSCRIPT_DESC
