# Contributing to remote-mcp

> 中文版本：[CONTRIBUTING.zh.md](./CONTRIBUTING.zh.md)

## Where to read first

Before changing anything significant:

1. The full design — [`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`](./docs/superpowers/specs/2026-05-26-remote-mcp-design.md). Many decisions (sentinel protocol, PTY allocation, setsid for background bash, reconnect WARNING protocol) have explicit rationales. Don't re-litigate without checking the spec first.
2. The architectural mental model — [`docs/explanation/architecture.md`](./docs/explanation/architecture.md).
3. The design decisions writeup — [`docs/explanation/design-decisions.md`](./docs/explanation/design-decisions.md) (decision + alternatives considered + rationale, per key choice).

## Dev setup

```bash
git clone <repo>
cd remote-mcp
pip install -e ".[dev]"
```

Requires Python 3.8+. Pulls in `paramiko`, `mcp`, `pyyaml`, plus dev extras (`pytest`, `pytest-asyncio`, `docker`).

## Running tests

Two layers:

```bash
# Unit (no SSH; fast)
pytest tests/unit/ -v

# Integration (requires reachable SSH host; slower)
pytest tests/integration/ -v

# Everything
pytest tests/ -v
```

### Integration tests require an SSH host

The default fixture targets `penglin_lb@192.168.10.20`. Override via env vars:

```bash
export RMCP_TEST_HOST=your.host
export RMCP_TEST_USER=youruser
export RMCP_TEST_PORT=22
export RMCP_TEST_KEY=~/.ssh/id_ed25519
pytest tests/integration/ -v
```

If the host is unreachable, integration tests are skipped — not failed.

Test isolation: each session creates a unique `/tmp/rmcp-test-<uuid>/` on the remote and cleans it up at session end. Background-bash test files `/tmp/rmcp-bg-*.log` are intentionally NOT auto-cleaned (left for post-mortem).

## Adding a new tool

That's its own how-to: [`docs/how-to/add-a-new-tool.md`](./docs/how-to/add-a-new-tool.md). It walks through the five touch points (tool function, schema, dispatch, tests, docs) with a concrete `Touch` example.

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

1. **All tools return strings.** Errors are `"Error: ..."` strings; tools never raise. The agent reads the string and adapts. See [`docs/reference/errors.md`](./docs/reference/errors.md) for the full catalog.
2. **Native-tool fidelity.** `Read`/`Write`/`Edit`/`MultiEdit`/`Bash`/`Glob`/`Grep` schemas and output formats match Claude Code's native tools verbatim. Don't add parameters or change output formats without a strong reason.
3. **Bandwidth awareness.** Anything that crosses the network is a cost center. Prefer server-side filtering (`Grep`), server-side slicing (`Read`), batching (`MultiRead`, `MultiEdit`), and SFTP-native ops where possible. See [`docs/explanation/bandwidth-and-latency.md`](./docs/explanation/bandwidth-and-latency.md).
4. **Single SSH Transport per process.** All file/exec/bash operations multiplex on one paramiko `Transport`. Don't open additional clients unless `ProxyJump` requires it. See [`docs/explanation/architecture.md`](./docs/explanation/architecture.md).
5. **Graceful reconnect.** SSH dies → one auto-reconnect attempt → next tool result gets a `[WARNING]` prefix with the host name so the agent knows shell state was reset. Never silently recover. See [`docs/explanation/reconnect-and-warning.md`](./docs/explanation/reconnect-and-warning.md).

## Filing your own feedback

If you're an agent using this tool and spot a bug or imagine a useful feature, use the `Feedback` tool. Output goes to `~/.local/share/remote-mcp/feedback.jsonl`. See [`docs/how-to/inspect-feedback-log.md`](./docs/how-to/inspect-feedback-log.md) for how the maintainer reads these.

## Where to ask

Open a GitHub issue. During private development, the Feedback log IS the issue tracker.
