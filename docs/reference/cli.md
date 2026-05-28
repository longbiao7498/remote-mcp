# CLI

> 中文版本：[cli.zh.md](./cli.zh.md)

## Synopsis

```
python -m remote_mcp --host <name> [--config <path>] [--cwd <path>] [--test]
```

## Arguments

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `--host <name>` | Yes | — | Logical host name to connect to. Must match a key under `hosts` in the config file. |
| `--config <path>` | No | `~/.config/remote-mcp/config.yaml` | Path to the YAML configuration file. `~` is expanded. |
| `--cwd <path>` | No | remote `$HOME` | Remote working directory. See `--cwd` section below. |
| `--test` | No | false | Run a smoke test instead of starting the MCP server (see Modes below). |

### `--cwd <path>`

Remote working directory. All tool relative paths resolve against this anchor. Must start with `/` (absolute), or be `~` / `~/...` (relative to remote user's `$HOME` — expanded at connect time).

- Overrides `hosts.<name>.cwd` from `config.yaml`.
- Default: remote `$HOME` (acts as `--cwd ~`).
- The configured cwd appears in every tool's output as `[host=X cwd=Y]` and in `RemoteInfo`.

Example:

```bash
python -m remote_mcp --host prod --cwd /opt/myapp
```

## Modes

### Normal (stdio MCP server)

Without `--test`, the process loads the configuration, resolves the jump host (if configured), opens an SSH connection to the named host, and runs the MCP server over stdio. The process blocks until the stdio streams are closed (i.e., until the MCP client — typically Claude Code — disconnects). On exit, the SSH connection is closed. Log output, if any, goes to stderr.

### --test (smoke test)

With `--test`, the process loads the configuration, opens an SSH connection to the named host, runs `echo OK` on the remote shell via a one-shot `exec` channel, and prints a one-line result to stdout, then exits. The SSH connection is closed before exit. Exit code 0 means the connection and basic exec are working; exit code 1 means the connection succeeded but the echo command did not produce the expected output.

Example output on success:

```
Connected to dev (alice@dev-internal.example.com). All tools: OK
```

Example output on unexpected echo response:

```
Connected but echo failed: 'something unexpected\n'
```

Connection failures (wrong host, auth error, network unreachable) surface as unhandled exceptions and produce a Python traceback on stderr with exit code 1.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Normal exit. In `--test` mode: connection and echo succeeded. In server mode: server shut down cleanly. |
| `1` | Error. In `--test` mode: connection succeeded but echo produced unexpected output, or an exception occurred. In server mode: startup failure (config not found, host not in config, SSH auth failed, etc.). |

## Environment variables

The following environment variables are read by the integration test suite. They are not used by the server itself.

| Variable | Description |
|----------|-------------|
| `RMCP_TEST_HOST` | Host name to use when running integration tests (maps to a `hosts` entry in the config). |
| `RMCP_TEST_CONFIG` | Path to the config file used during integration tests. Defaults to `~/.config/remote-mcp/config.yaml` if unset. |
