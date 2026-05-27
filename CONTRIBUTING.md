# Contributing to remote-mcp

## Project layout

```
remote_mcp/
├── __main__.py           CLI entry (--host, --config, --test)
├── server.py             MCP app: list_tools, call_tool, dispatch+retry
├── connection.py         SSHConnection: Transport, SFTP, ProxyJump, reconnect
├── bash_session.py       Persistent bash + sentinel protocol + reader thread
├── config.py             YAML → HostConfig / RootConfig dataclasses
├── schemas.py            JSON schemas + tool descriptions (M1 hints)
└── tools/
    ├── read.py write.py edit.py multi_edit.py multi_read.py file_stat.py
    └── bash.py glob.py grep.py feedback.py

docs/superpowers/
├── specs/2026-05-26-remote-mcp-design.md     authoritative design (v2)
└── plans/2026-05-26-remote-mcp-implementation.md   executed plan (31 tasks)
```

Read the spec end-to-end before touching architecture. Many decisions
(sentinel protocol, PTY allocation, setsid for background bash, reconnect
warning protocol) have explicit rationales — don't re-litigate without
checking spec §5 and §9 first.

## Dev setup

```bash
git clone <repo>
cd remote-mcp
pip install -e ".[dev]"   # paramiko + mcp + pyyaml + pytest + docker
```

## Running tests

Tests are split into two layers:

```bash
# Unit (no SSH, fast)
pytest tests/unit/ -v

# Integration (real SSH host, slow)
pytest tests/integration/ -v

# Full suite
pytest tests/ -v
```

### Integration tests need an SSH host

The default fixture targets `penglin_lb@192.168.10.20` (configured in
`tests/integration/conftest.py`). Override via env vars:

```bash
export RMCP_TEST_HOST=your.host
export RMCP_TEST_USER=youruser
export RMCP_TEST_PORT=22
export RMCP_TEST_KEY=~/.ssh/id_ed25519
pytest tests/integration/ -v
```

If the host is unreachable, integration tests are skipped (not failed).

### Test isolation

Each test session creates a unique workdir on the remote
(`/tmp/rmcp-test-<uuid>/`) and removes it at session end. Tests never modify
files outside this dir on the remote. **Background bash test files
(`/tmp/rmcp-bg-*.log`) are NOT auto-cleaned** — they're meant to persist
for post-mortem. `/tmp` cleanup handles them across reboots.

## Adding a new tool

If you want to add (say) a `Touch` tool:

1. **Implement** the function in `remote_mcp/tools/touch.py`:
   - Signature: `def touch(conn: SSHConnection, ...args) -> str`
   - On failure: return `"Error: ..."` string. **Never raise.**
   - If it uses the bash session, call `conn.get_bash_session()`.
   - If it uses SFTP, call `conn.get_sftp()`.
   - If it's a one-shot command, call `conn.exec(...)` — the server-level
     `_with_retry` wrapper will handle reconnect transparently.

2. **Register the schema** in `remote_mcp/schemas.py`:
   - Add `TOUCH_SCHEMA = {...}` (JSON Schema dict)
   - Add `TOUCH_DESC = "..."` (one paragraph; mention any bandwidth implication)
   - Append both to `ALL_TOOL_SCHEMAS` and `ALL_TOOL_DESCRIPTIONS` dicts

3. **Wire dispatch** in `remote_mcp/server.py`:
   - Add `from .tools import touch as touch_tool` to the imports
   - Add an `if name == "Touch": return touch_tool.touch(_conn, **args)` branch
     to `_raw_dispatch`

4. **Test**:
   - Unit-test pure logic in `tests/unit/test_touch_logic.py` (if any)
   - Integration-test SSH behavior in `tests/integration/test_file_tools.py`
     (or create a new file)
   - Reuse the `conn` fixture from existing test files

5. **Update docs**:
   - Add to `README.md` tools list
   - Add to `CHANGELOG.md` under `[Unreleased]` or next version
   - If it changes user workflow, update `CLAUDE.md.fragment.md`
   - Update spec §4 tool count if necessary

## Commit style

Conventional commits, in English:

```
feat(tools): Touch — create empty file or update mtime
fix(connection): expand ~ in key_path
docs: clarify Bash run_in_background usage
test(bash_session): cover ANSI escape stripping
build: bump paramiko to 3.4
```

## Design pillars (don't violate without discussion)

1. **All tools return strings.** Errors are `"Error: ..."` strings. Tools
   never raise. The agent reads the string and adapts.
2. **Native-tool fidelity.** Read/Write/Edit/MultiEdit/Bash/Glob/Grep schemas
   and output formats match Claude Code's native tools verbatim. Don't add
   parameters or change output formats without a strong reason.
3. **Bandwidth awareness.** Anything that crosses the network is a cost
   center. Prefer server-side filtering (Grep), server-side slicing (Read),
   batching (MultiRead, MultiEdit), and SFTP-native ops over shell wrappers
   where possible.
4. **Single SSH transport per process.** All file/exec/bash operations
   multiplex on one paramiko Transport. Don't open additional clients
   unless ProxyJump requires it.
5. **Graceful reconnect.** SSH dies → one auto-reconnect attempt → next
   tool result gets a `[WARNING]` prefix with the host name so the agent
   knows shell state was reset. Never silently recover.

## Filing your own feedback

If you're an agent using this tool and you spot a bug or a missing feature,
use the `Feedback` tool. Output goes to
`~/.local/share/remote-mcp/feedback.jsonl`. Maintainer reads it when
planning the next iteration.

## Where to ask

For now: open a GitHub issue (when the repo is public) or file a Feedback
entry. The Feedback file IS the issue tracker during private development.
