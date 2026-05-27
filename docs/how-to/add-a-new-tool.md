# Add a new tool

> 中文版本：[add-a-new-tool.zh.md](./add-a-new-tool.zh.md)

## When to use this guide

You want to expose a new remote capability to Claude Code — for example, a `Touch` tool, a `Chmod` tool, or a `Symlink` tool. This guide walks through all five touch points from implementation to docs.

## What you need first

- A local dev install: `pip install -e ".[dev]"` (installs pytest alongside the package)
- The full design spec read end-to-end: `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` — decisions about sentinel protocol, exec vs bash session, and SFTP vs shell are made there
- Familiarity with the existing tools in `remote_mcp/tools/` as reference implementations

## Steps

The example throughout is a `Touch` tool that creates an empty file or updates its mtime.

---

1. **Implement the tool function in `remote_mcp/tools/touch.py`**

   Follow the signature and return conventions exactly:

   ```python
   from ..connection import SSHConnection
   import shlex

   def touch(conn: SSHConnection, file_path: str) -> str:
       """Create an empty file or update its mtime."""
       result = conn.exec(f"touch {shlex.quote(file_path)}")
       if result.exit_code != 0:
           return f"Error: {result.stderr.strip() or 'touch failed'}"
       return f"Touched: {file_path}"
   ```

   Conventions to respect:

   - **Signature**: `def <name>(conn: SSHConnection, ...args) -> str`
   - **Failures**: return `"Error: ..."` — never raise.
   - **Execution path choice**:
     - `conn.exec(cmd)` — stateless, one-shot. Use for Glob/Grep-style operations and anything that does not need shell state.
     - `conn.get_bash_session().execute(cmd)` — stateful persistent shell. Use only if the tool needs `cd` or `export` state to persist.
     - `conn.get_sftp()` — for file read/write/mkdir. Binary-safe, no shell escaping.
   - `conn.exec()` calls are automatically retried on reconnect by the server's `_with_retry` wrapper — you get reconnect safety for free.

2. **Register the schema in `remote_mcp/schemas.py`**

   Add a `TOUCH_SCHEMA` dict and a `TOUCH_DESC` string, then append them to the export dicts at the bottom of the file:

   ```python
   TOUCH_SCHEMA = {
       "type": "object",
       "properties": {
           "file_path": {"type": "string", "description": "Absolute path on the remote host"},
       },
       "required": ["file_path"],
   }

   TOUCH_DESC = (
       "Create an empty file or update its modification time on the remote host. "
       "Equivalent to the shell `touch` command. "
       "Bandwidth: negligible (exec channel only)."
   )
   ```

   In the existing export dicts at the end of `schemas.py`:

   ```python
   ALL_TOOL_SCHEMAS = {
       ...,
       "Touch": TOUCH_SCHEMA,
   }

   ALL_TOOL_DESCRIPTIONS = {
       ...,
       "Touch": TOUCH_DESC,
   }
   ```

   The key (`"Touch"`) is the tool name that Claude Code will call.

3. **Wire dispatch in `remote_mcp/server.py`**

   Add the import at the top of the imports block:

   ```python
   from .tools import touch as touch_tool
   ```

   Add a branch in `_raw_dispatch`:

   ```python
   if name == "Touch":
       return touch_tool.touch(_conn, **args)
   ```

   Insert it in alphabetical order with the other branches to keep the file readable.

4. **Write tests**

   Unit tests (no SSH needed) go in `tests/unit/test_touch_logic.py`. Integration tests (real SSH) go in `tests/integration/test_file_tools.py` or a new file using the shared `conn` fixture.

   Minimal integration test:

   ```python
   def test_touch_creates_file(conn, remote_tmp):
       path = f"{remote_tmp}/testfile.txt"
       result = touch(conn, path)
       assert result == f"Touched: {path}"
       # verify it exists
       stat_result = conn.exec(f"test -f {shlex.quote(path)} && echo exists")
       assert "exists" in stat_result.stdout

   def test_touch_bad_path_returns_error(conn):
       result = touch(conn, "/root/no-permission-dir/x.txt")
       assert result.startswith("Error:")
   ```

   Run unit tests: `pytest tests/unit/ -v`
   Run integration tests: `pytest tests/integration/ -v` (skipped if SSH host unreachable)

5. **Update docs**

   - `README.md` — add `Touch` to the tools list in the intro paragraph.
   - `CHANGELOG.md` — add an entry under `[Unreleased]`:
     ```
     feat(tools): Touch — create empty file or update mtime
     ```
   - `CLAUDE.md.fragment.md` — add a usage hint if the new tool changes agent workflow.
   - The spec (`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`) §4 tool count — update if the total changes.

---

## Verification

1. Start the server manually and confirm no import errors:
   ```bash
   python -m remote_mcp --host prod --test
   ```

2. In Claude Code (after restart), call the new tool:
   ```
   mcp__remote-prod__Touch(file_path="/tmp/hello.txt")
   ```

   Expected: `Touched: /tmp/hello.txt`

3. Run the full test suite:
   ```bash
   pytest tests/ -v
   ```

## When this doesn't work

- **`Tool name not handled` error from the server** — the tool name in `ALL_TOOL_SCHEMAS`, `ALL_TOOL_DESCRIPTIONS`, and the `_raw_dispatch` branch must all match exactly (including case).
- **Tool appears in Claude Code but always returns `Error: ...`** — run the underlying exec command manually via `Bash` to isolate whether the error is in the SSH command or in the Python wrapper logic.
- **Schema validation failure from the MCP layer** — verify your schema's `required` list matches the function's non-default parameters exactly. Missing or extra entries cause the MCP framework to reject the call before it reaches your function.
