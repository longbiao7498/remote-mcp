"""JSON schemas for all 10 tools. See spec §6."""

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
        "description": {"type": "string", "default": ""},
        "timeout": {"type": "number", "default": 120},
        "run_in_background": {"type": "boolean", "default": False},
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

ALL_TOOL_DESCRIPTIONS = {
    "Read": READ_DESC, "Write": WRITE_DESC, "Edit": EDIT_DESC,
    "MultiEdit": MULTIEDIT_DESC, "MultiRead": MULTIREAD_DESC,
    "FileStat": FILESTAT_DESC, "Bash": BASH_DESC, "Glob": GLOB_DESC,
    "Grep": GREP_DESC, "Feedback": FEEDBACK_DESC,
}
