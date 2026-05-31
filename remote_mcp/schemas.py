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
    "Execute a shell command on the remote server. Shell state (cwd, env vars) persists across foreground calls. "
    "Command output is transferred over SSH. Batch related commands with '&&'; pipe large outputs through head/tail. "
    "For long-running commands (build/test/install) set run_in_background=true — returns immediately with PID and log path; "
    "poll output via Read on the log; clean up with the printed kill command."
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
