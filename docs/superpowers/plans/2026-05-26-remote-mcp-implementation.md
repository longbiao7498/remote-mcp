# remote-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v2 remote-mcp Python MCP server per `docs/superpowers/specs/2026-05-26-remote-mcp-design.md` — a local stdio MCP server that proxies 10 tools (Read, Write, Edit, MultiEdit, MultiRead, FileStat, Bash, Glob, Grep, Feedback) over SSH to a remote Linux host.

**Architecture:** Long-lived Python process per remote host. One paramiko `Transport` (compress=on, keepalive=30s) per process, multiplexing a persistent bash channel (sentinel-protocol command boundaries + cwd capture), a lazy SFTP client (file ops + metadata), and ephemeral exec channels (Glob/Grep/MultiRead/Read sed-slicing). Auto-reconnect once on drop; prefix subsequent tool results with `[WARNING]` carrying the host name. Bash supports background mode via `setsid nohup ... &` returning PID/PGID for clean process-group kills. Feedback tool appends agent-filed dev-loop notes to a local JSONL file.

**Tech Stack:** Python 3.8+, paramiko (SSH), mcp (Anthropic MCP SDK), pyyaml (config), pytest + pytest-asyncio + docker (testing). No code lives on the remote side.

---

## Reading Order

Read these spec sections before starting; everything below references them:
- §5.1 / §5.1.1 (connection lifecycle) — Stage 1
- §5.2 (sentinel protocol) — Stage 2
- §5.3.1 – §5.3.10 (one per tool) — Stages 3-5
- §5.4 (server.py) — Stage 5
- §6 (interface table, error wording) — all stages
- §11 (config schema) — Stage 1
- §13 (acceptance criteria per stage) — final verification

## File Structure

```
remote-mcp/
├── pyproject.toml                    # Stage 0
├── README.md                          # Stage 6
├── CLAUDE.md.fragment.md              # Stage 6 (user-facing M2 doc)
├── remote_mcp/
│   ├── __init__.py                    # Stage 0
│   ├── __main__.py                    # Stage 6
│   ├── config.py                      # Stage 1 (HostConfig, load_config)
│   ├── connection.py                  # Stage 1 (SSHConnection, ExecResult)
│   ├── bash_session.py                # Stage 2 (BashSession, sentinel)
│   ├── server.py                      # Stage 5 (MCP app, main())
│   ├── schemas.py                     # Stage 5 (JSON schemas for tools)
│   └── tools/
│       ├── __init__.py                # Stage 3
│       ├── read.py                    # Stage 3
│       ├── write.py                   # Stage 3
│       ├── edit.py                    # Stage 3
│       ├── multi_edit.py              # Stage 3
│       ├── multi_read.py              # Stage 3
│       ├── file_stat.py               # Stage 3
│       ├── glob.py                    # Stage 4
│       ├── grep.py                    # Stage 4
│       ├── bash.py                    # Stage 5
│       └── feedback.py                # Stage 5
└── tests/
    ├── conftest.py                    # Stage 0
    ├── unit/                          # Pure-logic tests, no SSH
    │   ├── test_config.py
    │   ├── test_glob_pattern.py
    │   ├── test_sentinel_parser.py
    │   ├── test_multi_edit_logic.py
    │   ├── test_feedback_logic.py
    │   └── test_schemas.py
    └── integration/                   # Tests against real sshd container
        ├── conftest.py                # sshd container fixture
        ├── test_connection.py
        ├── test_bash_session.py
        ├── test_file_tools.py
        ├── test_search_tools.py
        ├── test_bash_tool.py
        ├── test_feedback_tool.py
        └── test_server.py
```

## Testing Strategy

**Two test layers**:
1. **Unit tests** (`tests/unit/`): pure-logic helpers — glob pattern conversion, sentinel line parsing, MultiEdit atomicity logic, feedback JSON shape, config YAML parsing. No SSH, no docker. Fast.
2. **Integration tests** (`tests/integration/`): full end-to-end against a real sshd in a docker container. Slower but truthful — paramiko has too much state to mock usefully.

The sshd container fixture (`tests/integration/conftest.py`, Stage 0) is the foundation. Start it once per test session; reuse across all integration tests.

---

## Stage 0: Project Bootstrap

### Task 0.1: Create `pyproject.toml`

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create the pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "remote-mcp"
version = "0.1.0"
description = "Local MCP server proxying file/shell tools to a remote Linux host over SSH"
readme = "README.md"
requires-python = ">=3.8"
dependencies = [
    "paramiko>=3.0",
    "mcp>=0.9.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "docker>=6.0",
]

[project.scripts]
remote-mcp = "remote_mcp.__main__:cli"

[tool.setuptools.packages.find]
include = ["remote_mcp*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Install in editable mode**

Run: `pip install -e ".[dev]"`
Expected: Successful install, `remote_mcp` package importable.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pyproject.toml with paramiko + mcp + pyyaml deps"
```

---

### Task 0.2: Create package skeleton

**Files:**
- Create: `remote_mcp/__init__.py`
- Create: `remote_mcp/tools/__init__.py`

- [ ] **Step 1: Create empty package files**

`remote_mcp/__init__.py`:
```python
"""remote-mcp: stdio MCP server proxying tools to remote Linux hosts over SSH."""

__version__ = "0.1.0"
```

`remote_mcp/tools/__init__.py`:
```python
"""Tool implementations dispatched by server.call_tool()."""
```

- [ ] **Step 2: Verify import**

Run: `python -c "import remote_mcp; print(remote_mcp.__version__)"`
Expected: `0.1.0`

- [ ] **Step 3: Commit**

```bash
git add remote_mcp/__init__.py remote_mcp/tools/__init__.py
git commit -m "feat: add remote_mcp package skeleton"
```

---

### Task 0.3: Unit test conftest

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: Create empty conftest and test packages**

`tests/conftest.py`:
```python
"""Shared pytest configuration for both unit and integration tests."""
```

`tests/unit/__init__.py` and `tests/integration/__init__.py`: empty files.

- [ ] **Step 2: Verify pytest discovery**

Run: `pytest tests/ --collect-only -q`
Expected: `no tests collected` (no tests yet — that's correct).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py tests/unit/__init__.py tests/integration/__init__.py
git commit -m "test: scaffold tests/ with unit and integration subdirs"
```

---

### Task 0.4: Integration test fixture — sshd container

**Files:**
- Create: `tests/integration/conftest.py`

This is the foundation for all integration tests. The fixture spawns a `linuxserver/openssh-server` container, sets up a key pair, and yields connection params.

- [ ] **Step 1: Write the fixture**

`tests/integration/conftest.py`:
```python
"""Integration test fixtures: real sshd container via docker."""
import io
import os
import socket
import subprocess
import time
from pathlib import Path

import paramiko
import pytest


SSHD_IMAGE = "linuxserver/openssh-server:latest"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def ssh_key(tmp_path_factory):
    """Generate a fresh RSA key pair for the test session."""
    key_dir = tmp_path_factory.mktemp("ssh_keys")
    priv = key_dir / "id_rsa"
    subprocess.run(
        ["ssh-keygen", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(priv), "-q"],
        check=True,
    )
    pub = (key_dir / "id_rsa.pub").read_text().strip()
    return {"private_path": str(priv), "public_key": pub}


@pytest.fixture(scope="session")
def sshd_container(ssh_key):
    """Start an sshd container; yield {host, port, user, key_path}; tear down."""
    port = _free_port()
    name = f"remote-mcp-test-sshd-{port}"
    user = "testuser"

    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", name,
            "-p", f"{port}:2222",
            "-e", "PUID=1000", "-e", "PGID=1000",
            "-e", f"USER_NAME={user}",
            "-e", f"PUBLIC_KEY={ssh_key['public_key']}",
            "-e", "SUDO_ACCESS=true",
            "-e", "PASSWORD_ACCESS=false",
            SSHD_IMAGE,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    # Wait for sshd to accept connections
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                # Probe with paramiko to confirm SSH handshake works
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(
                    "127.0.0.1", port=port, username=user,
                    key_filename=ssh_key["private_path"], timeout=2,
                )
                c.close()
                break
        except (OSError, paramiko.SSHException):
            time.sleep(0.5)
    else:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL)
        pytest.fail("sshd container did not become ready in 30s")

    yield {
        "host": "127.0.0.1",
        "port": port,
        "user": user,
        "key_path": ssh_key["private_path"],
        "container": name,
    }

    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL)


@pytest.fixture
def sshd_kill_and_restart(sshd_container):
    """Helper for reconnect tests: restart the container."""
    def _action():
        subprocess.run(
            ["docker", "restart", sshd_container["container"]],
            check=True, stdout=subprocess.DEVNULL,
        )
        # Re-wait for readiness
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with socket.create_connection(
                    (sshd_container["host"], sshd_container["port"]), timeout=1
                ):
                    return
            except OSError:
                time.sleep(0.3)
        pytest.fail("sshd did not come back after restart")
    return _action
```

- [ ] **Step 2: Smoke test the fixture**

Create `tests/integration/test_smoke.py`:
```python
import paramiko

def test_can_connect_to_sshd(sshd_container, ssh_key):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        sshd_container["host"],
        port=sshd_container["port"],
        username=sshd_container["user"],
        key_filename=ssh_key["private_path"],
    )
    stdin, stdout, stderr = client.exec_command("echo hello")
    assert stdout.read().decode().strip() == "hello"
    client.close()
```

- [ ] **Step 3: Run the smoke test**

Run: `pytest tests/integration/test_smoke.py -v`
Expected: PASS (takes ~10s on first run while pulling image).

If `docker` daemon not running or image not pullable, fix that before continuing — this fixture is foundational.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_smoke.py
git commit -m "test: add sshd container fixture for integration tests"
```

---

## Stage 1: connection.py

References: spec §5.1, §5.1.1 (lifecycle), §9 (error/reconnect), §11 (config).

### Task 1.1: `config.py` — HostConfig + load_config

**Files:**
- Create: `remote_mcp/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:
```python
import textwrap
from pathlib import Path

import pytest

from remote_mcp.config import HostConfig, RootConfig, load_config


def test_load_minimal_config(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        hosts:
          prod:
            hostname: 10.0.0.1
            user: ubuntu
        default_host: prod
    """).strip())
    root = load_config(str(cfg))
    assert isinstance(root, RootConfig)
    assert root.default_host == "prod"
    assert root.hosts["prod"].hostname == "10.0.0.1"
    assert root.hosts["prod"].user == "ubuntu"
    # Defaults
    assert root.hosts["prod"].port == 22
    assert root.hosts["prod"].keepalive_interval == 30
    assert root.hosts["prod"].compression is True
    assert root.hosts["prod"].bash_timeout_default == 120
    assert root.feedback_path.endswith("feedback.jsonl")


def test_load_full_config_with_jump_host(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        hosts:
          jump:
            hostname: jump.example.com
            user: ops
            port: 2222
            key_path: ~/.ssh/jump_key
          internal:
            hostname: 10.0.0.50
            user: admin
            jump_host: jump
            compression: false
            bash_timeout_default: 300
        default_host: internal
        feedback_path: /tmp/feedback.jsonl
    """).strip())
    root = load_config(str(cfg))
    assert root.hosts["internal"].jump_host == "jump"
    assert root.hosts["internal"].compression is False
    assert root.hosts["internal"].bash_timeout_default == 300
    assert root.feedback_path == "/tmp/feedback.jsonl"


def test_load_config_missing_default_host(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("hosts:\n  prod:\n    hostname: x\n    user: y\n")
    # No default_host required if --host is passed; loader doesn't validate that
    root = load_config(str(cfg))
    assert root.default_host is None


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'HostConfig'` (or similar).

- [ ] **Step 3: Implement `remote_mcp/config.py`**

```python
"""Configuration loading. See spec §11."""
import os
import pathlib
from dataclasses import dataclass, field
from typing import Dict, Optional

import yaml


_DEFAULT_FEEDBACK_PATH = "~/.local/share/remote-mcp/feedback.jsonl"


@dataclass
class HostConfig:
    name: str                              # populated from the dict key
    hostname: str
    user: str
    port: int = 22
    key_path: Optional[str] = None
    password: Optional[str] = None
    jump_host: Optional[str] = None
    connect_timeout: float = 10.0
    keepalive_interval: int = 30
    compression: bool = True
    bash_timeout_default: int = 120
    glob_output_limit: int = 1000
    read_size_cap: int = 256 * 1024
    bash_output_cap: int = 100 * 1024


@dataclass
class RootConfig:
    hosts: Dict[str, HostConfig]
    default_host: Optional[str] = None
    feedback_path: str = _DEFAULT_FEEDBACK_PATH


def load_config(path: str) -> RootConfig:
    p = pathlib.Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(p.read_text()) or {}

    hosts = {}
    for name, fields in (raw.get("hosts") or {}).items():
        hosts[name] = HostConfig(name=name, **fields)

    return RootConfig(
        hosts=hosts,
        default_host=raw.get("default_host"),
        feedback_path=raw.get("feedback_path") or _DEFAULT_FEEDBACK_PATH,
    )
```

- [ ] **Step 4: Run tests pass**

Run: `pytest tests/unit/test_config.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/config.py tests/unit/test_config.py
git commit -m "feat(config): HostConfig + RootConfig + load_config()"
```

---

### Task 1.2: `connection.py` — SSHConnection.connect() with compression + keepalive

**Files:**
- Create: `remote_mcp/connection.py`
- Create: `tests/integration/test_connection.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_connection.py`:
```python
import pytest
from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection


@pytest.fixture
def host_config(sshd_container, ssh_key):
    return HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        keepalive_interval=10,
        compression=True,
    )


def test_connect_succeeds(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        assert conn._transport is not None
        assert conn._transport.is_active()
    finally:
        conn.close()


def test_connect_enables_keepalive(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        # paramiko's Transport.get_keepalive() returns the interval
        assert conn._transport.get_keepalive() == 10
    finally:
        conn.close()


def test_connect_enables_compression(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        # After handshake, local_compression should be a non-trivial codec name
        # (paramiko uses 'zlib@openssh.com' or 'zlib' when negotiated)
        assert conn._transport.local_compression not in (None, "none")
    finally:
        conn.close()


def test_close_releases_transport(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    conn.close()
    assert conn._transport is None or not conn._transport.is_active()
```

- [ ] **Step 2: Run test, see it fail**

Run: `pytest tests/integration/test_connection.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `remote_mcp/connection.py` (minimal connect/close)**

```python
"""SSH connection lifecycle. See spec §5.1, §5.1.1."""
from dataclasses import dataclass
from typing import Optional

import paramiko

from .config import HostConfig


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SSHConnection:
    def __init__(self, config: HostConfig):
        self.config = config
        self._transport: Optional[paramiko.Transport] = None
        self._client: Optional[paramiko.SSHClient] = None
        self._reconnected: bool = False

    def connect(self) -> None:
        """Build the SSH client + Transport. Idempotent: closes any prior."""
        if self._client is not None:
            self.close()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.config.hostname,
            "port": self.config.port,
            "username": self.config.user,
            "timeout": self.config.connect_timeout,
            "compress": self.config.compression,
        }
        if self.config.key_path:
            connect_kwargs["key_filename"] = self.config.key_path
        if self.config.password:
            connect_kwargs["password"] = self.config.password
        client.connect(**connect_kwargs)

        self._client = client
        self._transport = client.get_transport()
        if self.config.keepalive_interval > 0:
            self._transport.set_keepalive(self.config.keepalive_interval)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._transport = None
```

- [ ] **Step 4: Run tests, see them pass**

Run: `pytest tests/integration/test_connection.py -v -k "connect or close"`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/connection.py tests/integration/test_connection.py
git commit -m "feat(connection): SSHConnection.connect/close with compress + keepalive"
```

---

### Task 1.3: `connection.py` — exec() one-shot channel

**Files:**
- Modify: `remote_mcp/connection.py`
- Modify: `tests/integration/test_connection.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/integration/test_connection.py`:
```python
def test_exec_echo_hello(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        result = conn.exec("echo hello")
        assert result.stdout == "hello\n"
        assert result.exit_code == 0
        assert result.stderr == ""
    finally:
        conn.close()


def test_exec_nonzero_exit(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        result = conn.exec("cat /nonexistent/file")
        assert result.exit_code != 0
        assert "No such file" in result.stderr or "No such" in result.stderr
    finally:
        conn.close()


def test_exec_captures_stderr_separately(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        result = conn.exec("echo to_stdout; echo to_stderr >&2")
        assert "to_stdout" in result.stdout
        assert "to_stderr" in result.stderr
    finally:
        conn.close()
```

- [ ] **Step 2: Run, see FAIL**

Run: `pytest tests/integration/test_connection.py -v -k exec`
Expected: FAIL (`exec` method doesn't exist).

- [ ] **Step 3: Implement `exec()` in `connection.py`**

Add this method to `SSHConnection` (in `remote_mcp/connection.py`):

```python
    def exec(self, command: str, timeout: float = 30.0) -> ExecResult:
        """One-shot exec. Opens a new channel, runs cmd, closes."""
        if self._client is None:
            raise RuntimeError("SSHConnection not connected; call connect() first")
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return ExecResult(stdout=out, stderr=err, exit_code=exit_code)
```

- [ ] **Step 4: Run, see PASS**

Run: `pytest tests/integration/test_connection.py -v -k exec`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/connection.py tests/integration/test_connection.py
git commit -m "feat(connection): SSHConnection.exec() one-shot command execution"
```

---

### Task 1.4: `connection.py` — get_sftp() lazy

**Files:**
- Modify: `remote_mcp/connection.py`
- Modify: `tests/integration/test_connection.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/integration/test_connection.py`:
```python
def test_get_sftp_returns_client(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        sftp = conn.get_sftp()
        # Use it: list home dir
        listing = sftp.listdir(".")
        assert isinstance(listing, list)
    finally:
        conn.close()


def test_get_sftp_returns_same_instance(host_config):
    """Verify lazy + cached (no new channel per call)."""
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        s1 = conn.get_sftp()
        s2 = conn.get_sftp()
        assert s1 is s2
    finally:
        conn.close()
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_connection.py -v -k sftp`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `SSHConnection.__init__`:
```python
        self._sftp: Optional[paramiko.SFTPClient] = None
```

Add method:
```python
    def get_sftp(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            if self._client is None:
                raise RuntimeError("SSHConnection not connected")
            self._sftp = self._client.open_sftp()
        return self._sftp
```

Also update `close()` to clear `_sftp`:
```python
    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._transport = None
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_connection.py -v -k sftp`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/connection.py tests/integration/test_connection.py
git commit -m "feat(connection): get_sftp() lazy + cached SFTPClient"
```

---

### Task 1.5: `connection.py` — ProxyJump

**Files:**
- Modify: `remote_mcp/connection.py`

ProxyJump requires a second sshd container as jump. We add the jump variant of the fixture.

- [ ] **Step 1: Add jump-host fixture and test**

Append to `tests/integration/conftest.py`:
```python
@pytest.fixture(scope="session")
def sshd_jump_container(ssh_key):
    """A second sshd container to act as a jump host."""
    port = _free_port()
    name = f"remote-mcp-test-jump-{port}"
    user = "jumpuser"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", name,
            "-p", f"{port}:2222",
            "-e", "PUID=1000", "-e", "PGID=1000",
            "-e", f"USER_NAME={user}",
            "-e", f"PUBLIC_KEY={ssh_key['public_key']}",
            "-e", "PASSWORD_ACCESS=false",
            SSHD_IMAGE,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    # Wait for ready
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL)
        pytest.fail("jump sshd container not ready")

    yield {"host": "127.0.0.1", "port": port, "user": user,
           "key_path": ssh_key["private_path"], "container": name}
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL)
```

Append to `tests/integration/test_connection.py`:
```python
def test_connect_via_jump_host(sshd_container, sshd_jump_container, ssh_key):
    # Build configs: jump first, then target through jump
    from remote_mcp.config import HostConfig

    jump_cfg = HostConfig(
        name="jump",
        hostname=sshd_jump_container["host"],
        port=sshd_jump_container["port"],
        user=sshd_jump_container["user"],
        key_path=ssh_key["private_path"],
    )
    target_cfg = HostConfig(
        name="target",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        jump_host="jump",
    )

    conn = SSHConnection(target_cfg, jump_config=jump_cfg)
    conn.connect()
    try:
        result = conn.exec("hostname")
        assert result.exit_code == 0
        assert result.stdout.strip()
    finally:
        conn.close()
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_connection.py -v -k jump`
Expected: FAIL (jump_config kwarg doesn't exist).

- [ ] **Step 3: Implement ProxyJump in `SSHConnection`**

Update `__init__`:
```python
    def __init__(self, config: HostConfig, jump_config: Optional[HostConfig] = None):
        self.config = config
        self.jump_config = jump_config
        self._transport: Optional[paramiko.Transport] = None
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._jump_client: Optional[paramiko.SSHClient] = None
        self._reconnected: bool = False
```

Refactor `connect()`:
```python
    def connect(self) -> None:
        if self._client is not None:
            self.close()

        sock = None
        if self.jump_config is not None:
            self._jump_client = paramiko.SSHClient()
            self._jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            j_kwargs = {
                "hostname": self.jump_config.hostname,
                "port": self.jump_config.port,
                "username": self.jump_config.user,
                "timeout": self.jump_config.connect_timeout,
            }
            if self.jump_config.key_path:
                j_kwargs["key_filename"] = self.jump_config.key_path
            self._jump_client.connect(**j_kwargs)
            sock = self._jump_client.get_transport().open_channel(
                "direct-tcpip",
                (self.config.hostname, self.config.port),
                ("localhost", 0),
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.config.hostname,
            "port": self.config.port,
            "username": self.config.user,
            "timeout": self.config.connect_timeout,
            "compress": self.config.compression,
        }
        if sock is not None:
            connect_kwargs["sock"] = sock
        if self.config.key_path:
            connect_kwargs["key_filename"] = self.config.key_path
        if self.config.password:
            connect_kwargs["password"] = self.config.password
        client.connect(**connect_kwargs)

        self._client = client
        self._transport = client.get_transport()
        if self.config.keepalive_interval > 0:
            self._transport.set_keepalive(self.config.keepalive_interval)
```

Update `close()` to also close jump:
```python
    def close(self) -> None:
        if self._sftp is not None:
            try: self._sftp.close()
            except Exception: pass
            self._sftp = None
        if self._client is not None:
            try: self._client.close()
            except Exception: pass
            self._client = None
            self._transport = None
        if self._jump_client is not None:
            try: self._jump_client.close()
            except Exception: pass
            self._jump_client = None
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_connection.py -v -k jump`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/connection.py tests/integration/conftest.py tests/integration/test_connection.py
git commit -m "feat(connection): ProxyJump via open_channel(direct-tcpip)"
```

---

### Task 1.6: `connection.py` — reconnect flag + auto-reconnect

**Files:**
- Modify: `remote_mcp/connection.py`
- Modify: `tests/integration/test_connection.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/integration/test_connection.py`:
```python
def test_reconnect_flag_initially_false(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        assert conn.check_and_clear_reconnect_flag() is False
    finally:
        conn.close()


def test_exec_with_retry_recovers_after_disconnect(host_config, sshd_kill_and_restart):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        # First call: succeeds
        assert conn.exec_with_retry("echo first").stdout.strip() == "first"
        assert conn.check_and_clear_reconnect_flag() is False

        # Kill the container, then issue another exec
        sshd_kill_and_restart()
        result = conn.exec_with_retry("echo second")
        assert result.stdout.strip() == "second"

        # Reconnect flag was set; check_and_clear consumes it
        assert conn.check_and_clear_reconnect_flag() is True
        # Second check: cleared
        assert conn.check_and_clear_reconnect_flag() is False
    finally:
        conn.close()
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_connection.py -v -k reconnect`
Expected: FAIL (`check_and_clear_reconnect_flag`, `exec_with_retry` don't exist).

- [ ] **Step 3: Implement**

Add methods to `SSHConnection`:

```python
    def check_and_clear_reconnect_flag(self) -> bool:
        flag = self._reconnected
        self._reconnected = False
        return flag

    def _do_reconnect(self) -> None:
        """Tear down (if needed) and rebuild. Sets _reconnected=True on success."""
        self.close()
        self.connect()
        # Note: any persistent BashSession is now invalid; whoever holds it
        # must re-create. See bash_session integration in Task 2.5.
        self._reconnected = True

    def exec_with_retry(self, command: str, timeout: float = 30.0) -> ExecResult:
        """exec() with one-shot auto-reconnect on SSH-level failure."""
        try:
            return self.exec(command, timeout=timeout)
        except (paramiko.SSHException, EOFError, OSError) as e:
            try:
                self._do_reconnect()
            except Exception as e2:
                raise ConnectionError(
                    f"SSH connection to {self.config.name} lost and reconnect "
                    f"failed: {e2}"
                ) from e
            return self.exec(command, timeout=timeout)
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_connection.py -v -k reconnect`
Expected: 2 tests PASS. (The restart test takes ~10s.)

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/connection.py tests/integration/test_connection.py
git commit -m "feat(connection): auto-reconnect + reconnect-flag mechanism"
```

---

## Stage 2: bash_session.py

References: spec §5.2 (sentinel protocol, init sequence, reader thread).

### Task 2.1: BashSession skeleton + start() with init sequence

**Files:**
- Create: `remote_mcp/bash_session.py`
- Create: `tests/integration/test_bash_session.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_bash_session.py`:
```python
import time
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.bash_session import BashSession


@pytest.fixture
def session(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        bash_timeout_default=10,
    )
    conn = SSHConnection(cfg)
    conn.connect()
    s = BashSession(conn._transport, cfg)
    s.start()
    yield s
    s.close()
    conn.close()


def test_start_creates_running_channel(session):
    assert session._channel is not None
    assert not session._channel.closed
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_bash_session.py::test_start_creates_running_channel -v`
Expected: FAIL.

- [ ] **Step 3: Implement skeleton**

`remote_mcp/bash_session.py`:
```python
"""Persistent bash session with sentinel protocol. See spec §5.2."""
import queue
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

import paramiko

from .config import HostConfig


_INIT_SEQUENCE = (
    "set +m\n"
    "set +o histexpand\n"
    "export PS1=''\n"
    "export TERM=dumb\n"
    "exec 2>&1\n"
)


@dataclass
class BashResult:
    output: str
    exit_code: int


class BashSession:
    def __init__(self, transport: paramiko.Transport, config: HostConfig):
        self._transport = transport
        self.config = config
        self._channel: Optional[paramiko.Channel] = None
        self._output_queue: "queue.Queue[bytes]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()
        self._cwd: str = "~"   # Will be populated after first execute() captures real cwd

    def start(self) -> None:
        ch = self._transport.open_session()
        # Critical: combine stderr+stdout BEFORE bash starts (paramiko-side)
        ch.set_combine_stderr(True)
        ch.exec_command("bash --norc --noprofile")
        self._channel = ch
        # Inject init sequence
        self._channel.sendall(_INIT_SEQUENCE.encode("utf-8"))
        # Start reader (will be needed for execute(); started here so it's safe to call execute next)
        self._start_reader()
        # Drain initial echoes from init sequence so they don't contaminate the first execute()
        # Use a tiny no-op sentinel execute. We define execute() in next task, so for now
        # just sleep a short moment to let any startup noise flow into the queue.
        time.sleep(0.2)
        # Drain queue
        while not self._output_queue.empty():
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break

    def _start_reader(self) -> None:
        def reader():
            buf = b""
            while not self._stop_reader.is_set():
                if self._channel is None or self._channel.closed:
                    break
                try:
                    if self._channel.recv_ready():
                        data = self._channel.recv(4096)
                        if not data:
                            break
                        buf += data
                        # Split on \n, queue complete lines
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            self._output_queue.put(line + b"\n")
                    else:
                        # Short sleep to avoid spinning
                        self._stop_reader.wait(0.01)
                except Exception:
                    break
            # Flush any remaining buffer
            if buf:
                self._output_queue.put(buf)

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._stop_reader.set()
        if self._channel is not None and not self._channel.closed:
            try:
                self._channel.close()
            except Exception:
                pass
            self._channel = None
```

Add `import time` at the top of bash_session.py.

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_bash_session.py::test_start_creates_running_channel -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/bash_session.py tests/integration/test_bash_session.py
git commit -m "feat(bash_session): skeleton with init sequence + reader thread"
```

---

### Task 2.2: Sentinel parser (pure unit test first)

**Files:**
- Create: `tests/unit/test_sentinel_parser.py`
- Modify: `remote_mcp/bash_session.py`

- [ ] **Step 1: Write failing unit tests**

`tests/unit/test_sentinel_parser.py`:
```python
from remote_mcp.bash_session import parse_sentinel_line


def test_parse_sentinel_basic():
    line = "RMCP_SENTINEL_abc123_EXIT_0_CWD_/home/user\n"
    uuid = "abc123"
    parsed = parse_sentinel_line(line, uuid)
    assert parsed == (0, "/home/user")


def test_parse_sentinel_non_zero_exit():
    line = "RMCP_SENTINEL_xyz_EXIT_127_CWD_/tmp\n"
    assert parse_sentinel_line(line, "xyz") == (127, "/tmp")


def test_parse_sentinel_cwd_with_spaces():
    line = "RMCP_SENTINEL_u_EXIT_0_CWD_/home/user with space/dir\n"
    assert parse_sentinel_line(line, "u") == (0, "/home/user with space/dir")


def test_parse_sentinel_wrong_uuid_returns_none():
    line = "RMCP_SENTINEL_other_EXIT_0_CWD_/tmp\n"
    assert parse_sentinel_line(line, "mine") is None


def test_parse_sentinel_non_sentinel_returns_none():
    assert parse_sentinel_line("regular output line\n", "anything") is None
    assert parse_sentinel_line("", "anything") is None
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_sentinel_parser.py -v`
Expected: FAIL (`parse_sentinel_line` doesn't exist).

- [ ] **Step 3: Implement**

Add to `remote_mcp/bash_session.py` (module-level, before the class):

```python
_SENTINEL_RE = re.compile(
    r"^RMCP_SENTINEL_([a-f0-9]+)_EXIT_(\d+)_CWD_(.*)$"
)


def parse_sentinel_line(line: str, expected_uuid: str):
    """
    If `line` is a sentinel matching expected_uuid, return (exit_code, cwd).
    Otherwise return None.
    """
    m = _SENTINEL_RE.match(line.rstrip("\n"))
    if not m:
        return None
    uuid_in_line, exit_str, cwd = m.groups()
    if uuid_in_line != expected_uuid:
        return None
    return int(exit_str), cwd
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/unit/test_sentinel_parser.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/bash_session.py tests/unit/test_sentinel_parser.py
git commit -m "feat(bash_session): parse_sentinel_line helper + unit tests"
```

---

### Task 2.3: BashSession.execute() with sentinel protocol

**Files:**
- Modify: `remote_mcp/bash_session.py`
- Modify: `tests/integration/test_bash_session.py`

- [ ] **Step 1: Add failing integration tests**

Append to `tests/integration/test_bash_session.py`:
```python
def test_execute_echo(session):
    result = session.execute("echo hello")
    assert result.output.strip() == "hello"
    assert result.exit_code == 0


def test_execute_persists_cwd(session):
    session.execute("cd /tmp")
    result = session.execute("pwd")
    assert result.output.strip() == "/tmp"
    assert session.current_cwd() == "/tmp"


def test_execute_persists_env(session):
    session.execute("export FOO=bar_value_xyz")
    result = session.execute("echo $FOO")
    assert result.output.strip() == "bar_value_xyz"


def test_execute_special_chars_roundtrip(session):
    # Use a heredoc-free shell-quoted string with quotes, dollar, backslash
    raw = "it's a $test \"quoted\" \\backslash"
    # Use printf %s to avoid bash interpreting it
    result = session.execute(f"printf '%s' {repr(raw)}")
    # The output should be exactly the raw string
    assert raw in result.output


def test_execute_nonzero_exit(session):
    result = session.execute("false")
    assert result.exit_code == 1


def test_execute_captures_cwd_change_in_same_command(session):
    result = session.execute("cd /var && pwd")
    assert result.output.strip() == "/var"
    assert session.current_cwd() == "/var"
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_bash_session.py -v -k execute`
Expected: FAIL (no `execute` method).

- [ ] **Step 3: Implement `execute()` and `current_cwd()`**

Add methods to `BashSession`:

```python
    def execute(self, command: str, timeout: Optional[float] = None) -> BashResult:
        """
        Send command + sentinel echo, read until sentinel arrives.
        Sentinel format: RMCP_SENTINEL_<uuid>_EXIT_$?_CWD_$(pwd)
        Captures exit_code AND cwd in one round-trip.
        """
        if self._channel is None or self._channel.closed:
            raise RuntimeError("BashSession not started or channel closed")
        if timeout is None:
            timeout = float(self.config.bash_timeout_default)

        u = uuid.uuid4().hex
        sentinel_cmd = (
            f'{command}\n'
            f'echo "RMCP_SENTINEL_{u}_EXIT_$?_CWD_$(pwd)"\n'
        )
        self._channel.sendall(sentinel_cmd.encode("utf-8"))

        import time as _time
        deadline = _time.time() + timeout
        output_lines = []
        exit_code = None
        cwd = None

        while True:
            remaining = deadline - _time.time()
            if remaining <= 0:
                # Send Ctrl-C; raise; session survives
                try:
                    self._channel.sendall(b"\x03")
                except Exception:
                    pass
                raise TimeoutError(f"Command timed out after {timeout}s")
            try:
                line_bytes = self._output_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            line = line_bytes.decode("utf-8", errors="replace")
            parsed = parse_sentinel_line(line, u)
            if parsed is not None:
                exit_code, cwd = parsed
                break
            output_lines.append(line)

        output = "".join(output_lines)
        if cwd is not None:
            self._cwd = cwd

        return BashResult(output=output, exit_code=exit_code if exit_code is not None else -1)

    def current_cwd(self) -> str:
        return self._cwd
```

Also update `start()` to set initial cwd by running `pwd` once:

In `start()`, after the drain-queue step, add:
```python
        # Capture initial cwd
        try:
            self.execute("true", timeout=5.0)  # captures cwd via sentinel
        except Exception:
            pass
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_bash_session.py -v -k execute`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/bash_session.py tests/integration/test_bash_session.py
git commit -m "feat(bash_session): execute() with sentinel protocol + cwd capture"
```

---

### Task 2.4: BashSession timeout

**Files:**
- Modify: `tests/integration/test_bash_session.py`

The timeout path was implemented in Task 2.3; this task is the integration test that verifies it.

- [ ] **Step 1: Add the timeout test**

Append to `tests/integration/test_bash_session.py`:
```python
def test_execute_timeout_raises_and_session_survives(session):
    with pytest.raises(TimeoutError):
        session.execute("sleep 100", timeout=2)
    # Session should still be usable; sleep was Ctrl-C'd
    result = session.execute("echo recovered")
    assert "recovered" in result.output


def test_current_cwd_unchanged_on_timeout(session):
    session.execute("cd /tmp")
    pre_cwd = session.current_cwd()
    with pytest.raises(TimeoutError):
        session.execute("sleep 100", timeout=2)
    # cwd cached value should still reflect /tmp
    assert session.current_cwd() == pre_cwd
```

- [ ] **Step 2: Run**

Run: `pytest tests/integration/test_bash_session.py -v -k timeout`
Expected: 2 tests PASS. (Each takes ~2s.)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_bash_session.py
git commit -m "test(bash_session): verify timeout-without-killing-session behavior"
```

---

### Task 2.5: SSHConnection.get_bash_session() integration

**Files:**
- Modify: `remote_mcp/connection.py`
- Modify: `tests/integration/test_connection.py`

- [ ] **Step 1: Add failing test**

Append to `tests/integration/test_connection.py`:
```python
def test_get_bash_session_lazy_singleton(host_config):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        s1 = conn.get_bash_session()
        s2 = conn.get_bash_session()
        assert s1 is s2
        # Verify it works
        result = s1.execute("echo via_connection")
        assert "via_connection" in result.output
    finally:
        conn.close()


def test_reconnect_invalidates_bash_session(host_config, sshd_kill_and_restart):
    conn = SSHConnection(host_config)
    conn.connect()
    try:
        s_pre = conn.get_bash_session()
        s_pre.execute("cd /tmp")

        sshd_kill_and_restart()

        # exec_with_retry forces reconnect
        conn.exec_with_retry("echo touchstone")

        # Now get_bash_session should return a NEW session (state reset)
        s_post = conn.get_bash_session()
        assert s_post is not s_pre
        # cwd reset to $HOME
        result = s_post.execute("pwd")
        assert result.output.strip() != "/tmp"
    finally:
        conn.close()
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_connection.py -v -k bash_session`
Expected: FAIL (`get_bash_session` doesn't exist on connection).

- [ ] **Step 3: Implement**

Add to `SSHConnection.__init__`:
```python
        self._bash_session = None
```

Add method:
```python
    def get_bash_session(self):
        from .bash_session import BashSession
        if self._bash_session is None:
            if self._client is None or self._transport is None:
                raise RuntimeError("SSHConnection not connected")
            self._bash_session = BashSession(self._transport, self.config)
            self._bash_session.start()
        return self._bash_session
```

Update `close()` to clean up bash session:
```python
    def close(self) -> None:
        if self._bash_session is not None:
            try: self._bash_session.close()
            except Exception: pass
            self._bash_session = None
        # ... existing cleanup for _sftp, _client, _jump_client ...
```

Update `_do_reconnect()` to invalidate the bash session reference. After `self.close()`, the bash_session is already None; after `self.connect()`, a new one will be lazily created on next access. So just:
```python
    def _do_reconnect(self) -> None:
        self.close()
        self.connect()
        self._reconnected = True
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_connection.py -v -k bash_session`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/connection.py tests/integration/test_connection.py
git commit -m "feat(connection): get_bash_session() lazy singleton + reconnect invalidates"
```

---

## Stage 3: File Tools

References: spec §5.3.1-§5.3.6.

### Task 3.1: Read tool — sed slicing

**Files:**
- Create: `remote_mcp/tools/read.py`
- Create: `tests/integration/test_file_tools.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_file_tools.py`:
```python
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import read as read_tool


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    yield c
    c.close()


def _write_remote_file(conn, path: str, content: str):
    sftp = conn.get_sftp()
    parent = "/".join(path.split("/")[:-1])
    if parent:
        conn.exec(f"mkdir -p {parent}")
    with sftp.file(path, "w") as f:
        f.write(content.encode("utf-8"))


def test_read_basic(conn):
    _write_remote_file(conn, "/tmp/rmcp-test-read.txt", "line one\nline two\nline three\n")
    out = read_tool.read(conn, "/tmp/rmcp-test-read.txt")
    # Format: 5 spaces + lineno + tab + content (with trailing \n preserved per line)
    assert "     1\tline one\n" in out
    assert "     2\tline two\n" in out
    assert "     3\tline three\n" in out


def test_read_with_offset_limit(conn):
    _write_remote_file(
        conn, "/tmp/rmcp-test-read2.txt",
        "".join(f"line {i}\n" for i in range(1, 21)),
    )
    out = read_tool.read(conn, "/tmp/rmcp-test-read2.txt", offset=5, limit=3)
    # Should contain lines 5, 6, 7 only
    assert "     5\tline 5\n" in out
    assert "     7\tline 7\n" in out
    assert "     8\t" not in out
    assert "     4\t" not in out


def test_read_file_not_found(conn):
    out = read_tool.read(conn, "/tmp/rmcp-this-does-not-exist-12345")
    assert out.startswith("Error: File not found:")
    assert "/tmp/rmcp-this-does-not-exist-12345" in out


def test_read_size_cap(conn, monkeypatch):
    # Write a file larger than the cap
    cap = 1024
    long_line = "x" * 50 + "\n"
    content = long_line * 1000  # 51000 bytes total
    _write_remote_file(conn, "/tmp/rmcp-test-big.txt", content)
    # Override cap for test
    conn.config.read_size_cap = cap
    out = read_tool.read(conn, "/tmp/rmcp-test-big.txt")
    assert len(out) <= cap + 200   # plus truncation message
    assert "[truncated to" in out
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_file_tools.py -v -k read`
Expected: FAIL.

- [ ] **Step 3: Implement `remote_mcp/tools/read.py`**

```python
"""Read tool. See spec §5.3.1."""
import shlex

from ..connection import SSHConnection


def read(conn: SSHConnection, file_path: str,
         offset: int = 1, limit: int = 2000) -> str:
    if offset < 1:
        return f"Error: offset must be >= 1, got {offset}"
    if limit < 1:
        return f"Error: limit must be >= 1, got {limit}"

    end = offset + limit - 1
    # sed -n '<start>,<end>p; <end+1>q' file
    cmd = (
        f"sed -n '{offset},{end}p; {end+1}q' "
        f"{shlex.quote(file_path)}"
    )
    result = conn.exec(cmd)

    if result.exit_code != 0:
        stderr = result.stderr or ""
        if "No such file" in stderr or "cannot open" in stderr:
            return f"Error: File not found: {file_path}"
        return f"Error: {stderr.strip() or 'unknown error reading file'}"

    lines = result.stdout.splitlines(keepends=True)
    parts = []
    for i, line in enumerate(lines):
        parts.append(f"     {offset + i}\t{line}")
    out = "".join(parts)

    cap = conn.config.read_size_cap
    if len(out) > cap:
        out = out[:cap] + f"\n... [truncated to {cap} bytes]"
    return out
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_file_tools.py -v -k read`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/read.py tests/integration/test_file_tools.py
git commit -m "feat(tools): Read — remote sed slicing with size cap"
```

---

### Task 3.2: Write tool — SFTP recursive mkdir

**Files:**
- Create: `remote_mcp/tools/write.py`
- Modify: `tests/integration/test_file_tools.py`

- [ ] **Step 1: Failing tests**

Append to `tests/integration/test_file_tools.py`:
```python
from remote_mcp.tools import write as write_tool


def test_write_creates_file(conn):
    out = write_tool.write(conn, "/tmp/rmcp-write-test.txt", "hello world\n")
    assert out.startswith("Successfully wrote")
    # Verify
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-write-test.txt", "r") as f:
        assert f.read().decode() == "hello world\n"


def test_write_creates_parent_dirs(conn):
    path = "/tmp/rmcp-w-test/nested/sub/file.txt"
    # Clean up first if exists
    conn.exec(f"rm -rf /tmp/rmcp-w-test")
    out = write_tool.write(conn, path, "deep\n")
    assert "Successfully wrote" in out
    # Verify
    sftp = conn.get_sftp()
    with sftp.file(path, "r") as f:
        assert f.read().decode() == "deep\n"


def test_write_special_chars(conn):
    raw = "it's a $VAR with \"quotes\" and \\backslash\nplus newline"
    write_tool.write(conn, "/tmp/rmcp-w-special.txt", raw)
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-w-special.txt", "r") as f:
        assert f.read().decode() == raw
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_file_tools.py -v -k write`
Expected: FAIL.

- [ ] **Step 3: Implement**

`remote_mcp/tools/write.py`:
```python
"""Write tool. See spec §5.3.2."""
import posixpath

from ..connection import SSHConnection


def _sftp_mkdirs(sftp, path: str) -> None:
    """Recursive mkdir via SFTP only (no shell)."""
    if path in ("", "/", "."):
        return
    try:
        sftp.stat(path)
        return  # exists
    except IOError:
        pass
    parent = posixpath.dirname(path)
    if parent and parent != path:
        _sftp_mkdirs(sftp, parent)
    try:
        sftp.mkdir(path)
    except IOError:
        # Race: someone else created it
        pass


def write(conn: SSHConnection, file_path: str, content: str) -> str:
    sftp = conn.get_sftp()
    parent = posixpath.dirname(file_path)
    if parent:
        _sftp_mkdirs(sftp, parent)
    encoded = content.encode("utf-8")
    with sftp.file(file_path, "w") as f:
        f.write(encoded)
    return f"Successfully wrote {len(content)} characters to {file_path}"
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_file_tools.py -v -k write`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/write.py tests/integration/test_file_tools.py
git commit -m "feat(tools): Write — SFTP-native recursive mkdir + write"
```

---

### Task 3.3: Edit tool — read-modify-write with uniqueness

**Files:**
- Create: `remote_mcp/tools/edit.py`
- Modify: `tests/integration/test_file_tools.py`

- [ ] **Step 1: Failing tests**

Append:
```python
from remote_mcp.tools import edit as edit_tool


def test_edit_unique_match(conn):
    write_tool.write(conn, "/tmp/rmcp-edit-1.txt", "alpha\nbeta\ngamma\n")
    out = edit_tool.edit(conn, "/tmp/rmcp-edit-1.txt", "beta", "BETA")
    assert "Successfully edited" in out
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-edit-1.txt", "r") as f:
        assert f.read().decode() == "alpha\nBETA\ngamma\n"


def test_edit_zero_matches(conn):
    write_tool.write(conn, "/tmp/rmcp-edit-2.txt", "alpha\nbeta\n")
    out = edit_tool.edit(conn, "/tmp/rmcp-edit-2.txt", "missing_string", "X")
    assert out == "Error: old_string not found in /tmp/rmcp-edit-2.txt"


def test_edit_multiple_matches(conn):
    write_tool.write(conn, "/tmp/rmcp-edit-3.txt", "foo\nfoo\nfoo\n")
    out = edit_tool.edit(conn, "/tmp/rmcp-edit-3.txt", "foo", "bar")
    assert "old_string found 3 times" in out
    assert "/tmp/rmcp-edit-3.txt" in out
    # File unchanged
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-edit-3.txt", "r") as f:
        assert f.read().decode() == "foo\nfoo\nfoo\n"


def test_edit_file_not_found(conn):
    out = edit_tool.edit(conn, "/tmp/rmcp-edit-nope-xyz", "a", "b")
    assert out.startswith("Error: File not found:")
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_file_tools.py -v -k edit`
Expected: FAIL.

- [ ] **Step 3: Implement**

`remote_mcp/tools/edit.py`:
```python
"""Edit tool. See spec §5.3.3."""
from ..connection import SSHConnection


def edit(conn: SSHConnection, file_path: str,
         old_string: str, new_string: str,
         replace_all: bool = False) -> str:
    sftp = conn.get_sftp()
    try:
        with sftp.file(file_path, "r") as f:
            content = f.read().decode("utf-8")
    except IOError:
        return f"Error: File not found: {file_path}"

    if replace_all:
        if old_string not in content:
            return f"Error: old_string not found in {file_path}"
        new_content = content.replace(old_string, new_string)
    else:
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1:
            return (
                f"Error: old_string found {count} times in {file_path}. "
                f"Provide more context to match uniquely."
            )
        new_content = content.replace(old_string, new_string, 1)

    with sftp.file(file_path, "w") as f:
        f.write(new_content.encode("utf-8"))
    return f"Successfully edited {file_path}"
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_file_tools.py -v -k edit`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/edit.py tests/integration/test_file_tools.py
git commit -m "feat(tools): Edit — read-modify-write with uniqueness check"
```

---

### Task 3.4: MultiEdit — atomic batch

**Files:**
- Create: `remote_mcp/tools/multi_edit.py`
- Create: `tests/unit/test_multi_edit_logic.py`
- Modify: `tests/integration/test_file_tools.py`

MultiEdit has nontrivial pure-string logic — covered by unit tests; SFTP plumbing by an integration test.

- [ ] **Step 1: Unit tests (pure logic)**

`tests/unit/test_multi_edit_logic.py`:
```python
from remote_mcp.tools.multi_edit import apply_edits


def test_apply_edits_sequential():
    content = "alpha\nbeta\ngamma\n"
    edits = [
        {"old_string": "alpha", "new_string": "A"},
        {"old_string": "gamma", "new_string": "G"},
    ]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "A\nbeta\nG\n"


def test_apply_edits_uses_prior_result():
    """Each subsequent edit operates on the result of the prior."""
    content = "foo"
    edits = [
        {"old_string": "foo", "new_string": "bar"},
        {"old_string": "bar", "new_string": "baz"},
    ]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "baz"


def test_apply_edits_zero_match_fails_atomically():
    content = "foo bar"
    edits = [
        {"old_string": "foo", "new_string": "FOO"},
        {"old_string": "nothing", "new_string": "X"},  # fails
    ]
    out, err = apply_edits(content, edits)
    assert err is not None
    assert "edit #2" in err
    assert "old_string not found" in err
    assert out is None  # atomic: no partial result


def test_apply_edits_multi_match_without_replace_all_fails():
    content = "foo foo"
    edits = [{"old_string": "foo", "new_string": "X"}]
    out, err = apply_edits(content, edits)
    assert err is not None
    assert "edit #1" in err
    assert "found 2 times" in err


def test_apply_edits_replace_all():
    content = "foo foo foo"
    edits = [{"old_string": "foo", "new_string": "X", "replace_all": True}]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "X X X"
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_multi_edit_logic.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `tools/multi_edit.py`**

```python
"""MultiEdit tool. See spec §5.3.4."""
from typing import List, Dict, Tuple, Optional

from ..connection import SSHConnection


def apply_edits(content: str, edits: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply edits sequentially. Atomic: any failure returns (None, error_msg).
    Returns (new_content, None) on success.
    """
    current = content
    for i, e in enumerate(edits, start=1):
        old = e["old_string"]
        new = e["new_string"]
        replace_all = e.get("replace_all", False)
        if replace_all:
            if old not in current:
                return None, f"Error: edit #{i}: old_string not found"
            current = current.replace(old, new)
        else:
            count = current.count(old)
            if count == 0:
                return None, f"Error: edit #{i}: old_string not found"
            if count > 1:
                return None, (
                    f"Error: edit #{i}: old_string found {count} times. "
                    f"Provide more context or set replace_all=true."
                )
            current = current.replace(old, new, 1)
    return current, None


def multi_edit(conn: SSHConnection, file_path: str,
               edits: List[Dict]) -> str:
    if not edits:
        return "Error: edits list is empty"
    sftp = conn.get_sftp()
    try:
        with sftp.file(file_path, "r") as f:
            content = f.read().decode("utf-8")
    except IOError:
        return f"Error: File not found: {file_path}"

    new_content, err = apply_edits(content, edits)
    if err:
        return err

    with sftp.file(file_path, "w") as f:
        f.write(new_content.encode("utf-8"))
    return f"Successfully applied {len(edits)} edits to {file_path}"
```

- [ ] **Step 4: Unit tests PASS**

Run: `pytest tests/unit/test_multi_edit_logic.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Integration test**

Append to `tests/integration/test_file_tools.py`:
```python
from remote_mcp.tools import multi_edit as me_tool


def test_multi_edit_atomic_on_remote(conn):
    write_tool.write(conn, "/tmp/rmcp-me-1.txt", "alpha\nbeta\ngamma\n")
    out = me_tool.multi_edit(conn, "/tmp/rmcp-me-1.txt", [
        {"old_string": "alpha", "new_string": "A"},
        {"old_string": "gamma", "new_string": "G"},
    ])
    assert "Successfully applied 2 edits" in out
    sftp = conn.get_sftp()
    assert sftp.file("/tmp/rmcp-me-1.txt", "r").read().decode() == "A\nbeta\nG\n"


def test_multi_edit_failure_does_not_modify_file(conn):
    write_tool.write(conn, "/tmp/rmcp-me-2.txt", "alpha\nbeta\n")
    out = me_tool.multi_edit(conn, "/tmp/rmcp-me-2.txt", [
        {"old_string": "alpha", "new_string": "A"},
        {"old_string": "nope", "new_string": "X"},  # fails
    ])
    assert out.startswith("Error:")
    # File must be unchanged
    sftp = conn.get_sftp()
    assert sftp.file("/tmp/rmcp-me-2.txt", "r").read().decode() == "alpha\nbeta\n"
```

Run: `pytest tests/integration/test_file_tools.py -v -k multi_edit`
Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote_mcp/tools/multi_edit.py tests/unit/test_multi_edit_logic.py tests/integration/test_file_tools.py
git commit -m "feat(tools): MultiEdit — atomic batch edit on single file"
```

---

### Task 3.5: MultiRead — batch sed across files

**Files:**
- Create: `remote_mcp/tools/multi_read.py`
- Modify: `tests/integration/test_file_tools.py`

- [ ] **Step 1: Failing tests**

Append to `tests/integration/test_file_tools.py`:
```python
from remote_mcp.tools import multi_read as mr_tool


def test_multi_read_two_files(conn):
    write_tool.write(conn, "/tmp/rmcp-mr-a.txt", "AAA\nAAA2\n")
    write_tool.write(conn, "/tmp/rmcp-mr-b.txt", "BBB\nBBB2\n")
    out = mr_tool.multi_read(conn, [
        {"file_path": "/tmp/rmcp-mr-a.txt"},
        {"file_path": "/tmp/rmcp-mr-b.txt"},
    ])
    assert "===FILE: /tmp/rmcp-mr-a.txt===" in out
    assert "===FILE: /tmp/rmcp-mr-b.txt===" in out
    assert "     1\tAAA\n" in out
    assert "     1\tBBB\n" in out


def test_multi_read_missing_file_marker(conn):
    write_tool.write(conn, "/tmp/rmcp-mr-c.txt", "exists\n")
    out = mr_tool.multi_read(conn, [
        {"file_path": "/tmp/rmcp-mr-c.txt"},
        {"file_path": "/tmp/rmcp-does-not-exist-xyz"},
    ])
    assert "===FILE: /tmp/rmcp-mr-c.txt===" in out
    assert "NOT_FOUND" in out
    assert "/tmp/rmcp-does-not-exist-xyz" in out


def test_multi_read_with_offset_limit(conn):
    write_tool.write(conn, "/tmp/rmcp-mr-d.txt",
                     "".join(f"line {i}\n" for i in range(1, 11)))
    out = mr_tool.multi_read(conn, [
        {"file_path": "/tmp/rmcp-mr-d.txt", "offset": 5, "limit": 2},
    ])
    assert "     5\tline 5\n" in out
    assert "     6\tline 6\n" in out
    assert "     4\t" not in out
    assert "     7\t" not in out


def test_multi_read_empty_list(conn):
    out = mr_tool.multi_read(conn, [])
    assert out.startswith("Error:")
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_file_tools.py -v -k multi_read`
Expected: FAIL.

- [ ] **Step 3: Implement**

`remote_mcp/tools/multi_read.py`:
```python
"""MultiRead tool. See spec §5.3.5."""
import re
import shlex
from typing import List, Dict

from ..connection import SSHConnection


_MARKER_BEGIN_RE = re.compile(r"^===RMCP_FILE_BEGIN:(.+)===$")
_MARKER_END_RE = re.compile(r"^===RMCP_FILE_END:(.+):(OK|NOT_FOUND)===$")


def multi_read(conn: SSHConnection, reads: List[Dict]) -> str:
    if not reads:
        return "Error: reads list is empty"

    # Build shell script: for each read, emit BEGIN marker, then sed, then END marker
    script_parts = []
    for r in reads:
        fp = r["file_path"]
        offset = r.get("offset", 1)
        limit = r.get("limit", 2000)
        end = offset + limit - 1
        qfp = shlex.quote(fp)
        script_parts.append(
            f'echo "===RMCP_FILE_BEGIN:{fp}==="; '
            f'if [ -f {qfp} ]; then '
            f"  sed -n '{offset},{end}p; {end+1}q' {qfp}; "
            f'  echo "===RMCP_FILE_END:{fp}:OK==="; '
            f'else '
            f'  echo "===RMCP_FILE_END:{fp}:NOT_FOUND==="; '
            f'fi'
        )
    cmd = "; ".join(script_parts)
    result = conn.exec(cmd, timeout=60.0)
    if result.exit_code != 0 and not result.stdout:
        return f"Error: {result.stderr.strip() or 'multi_read failed'}"

    # Parse the output into per-file chunks
    return _format_multi_read_output(result.stdout, reads, conn.config.read_size_cap)


def _format_multi_read_output(raw: str, reads: List[Dict], cap: int) -> str:
    """Split raw output by BEGIN/END markers; add line-number prefixes per file."""
    out_chunks = []
    lines = raw.splitlines(keepends=True)
    i = 0
    read_index = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        m_begin = _MARKER_BEGIN_RE.match(line)
        if m_begin:
            file_path = m_begin.group(1)
            offset = reads[read_index].get("offset", 1)
            # Collect content lines until END marker
            content_lines = []
            i += 1
            while i < len(lines):
                inner = lines[i]
                m_end = _MARKER_END_RE.match(inner.rstrip("\n"))
                if m_end:
                    status = m_end.group(2)
                    if status == "NOT_FOUND":
                        out_chunks.append(f"===FILE: {file_path} (NOT FOUND)===\n\n")
                    else:
                        header = f"===FILE: {file_path}===\n"
                        body = "".join(
                            f"     {offset + j}\t{l}"
                            for j, l in enumerate(content_lines)
                        )
                        out_chunks.append(header + body + "\n")
                    i += 1
                    read_index += 1
                    break
                content_lines.append(inner)
                i += 1
        else:
            i += 1

    out = "".join(out_chunks)
    if len(out) > cap:
        out = out[:cap] + f"\n... [truncated to {cap} bytes]"
    return out
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_file_tools.py -v -k multi_read`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/multi_read.py tests/integration/test_file_tools.py
git commit -m "feat(tools): MultiRead — batch sed across files in one round-trip"
```

---

### Task 3.6: FileStat — SFTP stat

**Files:**
- Create: `remote_mcp/tools/file_stat.py`
- Modify: `tests/integration/test_file_tools.py`

- [ ] **Step 1: Failing tests**

Append:
```python
from remote_mcp.tools import file_stat as fs_tool


def test_file_stat_existing_file(conn):
    write_tool.write(conn, "/tmp/rmcp-fs-1.txt", "abc")
    out = fs_tool.file_stat(conn, "/tmp/rmcp-fs-1.txt")
    assert "exists=true" in out
    assert "type=file" in out
    assert "size=3" in out
    assert "mtime=" in out


def test_file_stat_missing(conn):
    out = fs_tool.file_stat(conn, "/tmp/rmcp-fs-does-not-exist-xyz")
    assert out == "/tmp/rmcp-fs-does-not-exist-xyz: exists=false"


def test_file_stat_directory(conn):
    conn.exec("mkdir -p /tmp/rmcp-fs-dir")
    out = fs_tool.file_stat(conn, "/tmp/rmcp-fs-dir")
    assert "exists=true" in out
    assert "type=dir" in out


def test_file_stat_list_input(conn):
    write_tool.write(conn, "/tmp/rmcp-fs-list-a.txt", "a")
    write_tool.write(conn, "/tmp/rmcp-fs-list-b.txt", "bb")
    out = fs_tool.file_stat(conn, [
        "/tmp/rmcp-fs-list-a.txt",
        "/tmp/rmcp-fs-list-b.txt",
        "/tmp/rmcp-fs-nope",
    ])
    lines = out.splitlines()
    assert len(lines) == 3
    assert "size=1" in lines[0]
    assert "size=2" in lines[1]
    assert lines[2].endswith("exists=false")
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_file_tools.py -v -k file_stat`
Expected: FAIL.

- [ ] **Step 3: Implement**

`remote_mcp/tools/file_stat.py`:
```python
"""FileStat tool. See spec §5.3.6."""
import stat as _stat
from datetime import datetime, timezone
from typing import List, Union

from ..connection import SSHConnection


def file_stat(conn: SSHConnection,
              file_paths: Union[str, List[str]]) -> str:
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    if not file_paths:
        return "Error: file_paths is empty"

    sftp = conn.get_sftp()
    lines = []
    for fp in file_paths:
        try:
            st = sftp.stat(fp)
        except IOError:
            lines.append(f"{fp}: exists=false")
            continue
        except PermissionError:
            lines.append(f"{fp}: error=permission_denied")
            continue

        mode = st.st_mode or 0
        if _stat.S_ISDIR(mode):
            kind = "dir"
        elif _stat.S_ISLNK(mode):
            kind = "symlink"
        else:
            kind = "file"
        mtime_iso = (
            datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            .isoformat(timespec="seconds")
        )
        lines.append(
            f"{fp}: exists=true type={kind} size={st.st_size} "
            f"mode={oct(mode)[-4:]} mtime={mtime_iso}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_file_tools.py -v -k file_stat`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/file_stat.py tests/integration/test_file_tools.py
git commit -m "feat(tools): FileStat — SFTP-native metadata lookup, single or batch"
```

---

## Stage 4: Search Tools

References: spec §5.3.8 (Glob), §5.3.9 (Grep with extended params).

### Task 4.1: Glob — pattern conversion (pure unit) + cap

**Files:**
- Create: `remote_mcp/tools/glob.py`
- Create: `tests/unit/test_glob_pattern.py`
- Create: `tests/integration/test_search_tools.py`

- [ ] **Step 1: Unit tests for pattern conversion**

`tests/unit/test_glob_pattern.py`:
```python
from remote_mcp.tools.glob import _glob_to_find_expr


def test_simple_filename():
    # "*.py" → -name '*.py'
    assert _glob_to_find_expr("*.py") == "-name '*.py'"


def test_recursive_double_star_filename():
    # "**/*.py" → equivalent to -name '*.py' (find recurses by default)
    assert _glob_to_find_expr("**/*.py") == "-name '*.py'"


def test_path_segment_pattern():
    # "src/*.c" → -wholename '*/src/*.c'
    # (* matches a single segment; the leading */ allows match at any depth)
    assert _glob_to_find_expr("src/*.c") == "-wholename '*/src/*.c'"


def test_path_with_recursive():
    # "src/**/*.py" → -wholename '*/src/*/*.py' OR similar
    # Implementation: replace ** with * (find -wholename '*' matches multiple segments
    # because globstar isn't honored by find by default; we use -wholename which
    # matches the entire path against the shell glob, with * spanning segments).
    assert _glob_to_find_expr("src/**/*.py") == "-wholename '*/src/*/*.py'"
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_glob_pattern.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_glob_to_find_expr`**

`remote_mcp/tools/glob.py`:
```python
"""Glob tool. See spec §5.3.8."""
import shlex

from ..connection import SSHConnection


def _glob_to_find_expr(pattern: str) -> str:
    """
    Convert a glob pattern into a `find` expression.

    Rules:
      "*.ext"           → -name '*.ext'              (filename only, any depth)
      "**/*.ext"        → -name '*.ext'              (recursive filename)
      "dir/*.ext"       → -wholename '*/dir/*.ext'   (path segment + filename)
      "dir/**/*.ext"    → -wholename '*/dir/*/*.ext' (path segments + recursive)

    Find's -wholename matches the full path against the shell glob.
    A leading "*/" makes the path-segment patterns match at any depth.

    The '**' (globstar) is collapsed to '*' for find's purposes; this is the
    documented approximation. Spec §14 lists this as a known limitation.
    """
    if "/" not in pattern:
        # Pure filename pattern
        return f"-name '{pattern}'"
    # First, normalize ** to * (find's -wholename doesn't honor globstar)
    normalized = pattern.replace("**", "*")
    # Strip leading "*/" if pattern already starts with one to avoid "**"
    # Then prepend "*/" so the pattern matches at any depth
    if not normalized.startswith("*/"):
        normalized = "*/" + normalized
    return f"-wholename '{normalized}'"


def glob_tool(conn: SSHConnection, pattern: str, path: str = ".") -> str:
    find_expr = _glob_to_find_expr(pattern)
    limit = conn.config.glob_output_limit
    # Use bash -c so the quoting in find_expr is preserved
    cmd = (
        f"find {shlex.quote(path)} "
        f"\\( {find_expr} \\) -type f 2>/dev/null "
        f"| sort | head -{limit + 1}"   # +1 to detect truncation
    )
    result = conn.exec(cmd)
    if result.exit_code not in (0, 1):
        return f"Error: {result.stderr.strip()}"

    lines = result.stdout.splitlines()
    if not lines:
        return "No files found matching pattern"

    if len(lines) > limit:
        truncated = "\n".join(lines[:limit])
        return truncated + f"\n... [truncated to {limit} entries]"
    return result.stdout
```

- [ ] **Step 4: Unit tests PASS**

Run: `pytest tests/unit/test_glob_pattern.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Integration test**

`tests/integration/test_search_tools.py`:
```python
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import glob as glob_tool
from remote_mcp.tools import write as write_tool


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    # Set up a test tree
    c.exec("rm -rf /tmp/rmcp-glob-test && mkdir -p /tmp/rmcp-glob-test/src/sub")
    write_tool.write(c, "/tmp/rmcp-glob-test/a.py", "x")
    write_tool.write(c, "/tmp/rmcp-glob-test/b.txt", "x")
    write_tool.write(c, "/tmp/rmcp-glob-test/src/c.py", "x")
    write_tool.write(c, "/tmp/rmcp-glob-test/src/sub/d.py", "x")
    yield c
    c.close()


def test_glob_simple_pattern(conn):
    out = glob_tool.glob_tool(conn, "*.py", "/tmp/rmcp-glob-test")
    assert "a.py" in out
    assert "c.py" in out
    assert "d.py" in out
    assert "b.txt" not in out


def test_glob_path_segment(conn):
    out = glob_tool.glob_tool(conn, "src/**/*.py", "/tmp/rmcp-glob-test")
    assert "src/c.py" in out or "src/sub/d.py" in out
    # Should NOT match top-level a.py
    assert "/a.py" not in out.replace("/src/", "/SRC/")  # simple disambig


def test_glob_no_matches(conn):
    out = glob_tool.glob_tool(conn, "*.nonexistent", "/tmp/rmcp-glob-test")
    assert out == "No files found matching pattern"
```

Run: `pytest tests/integration/test_search_tools.py -v -k glob`
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add remote_mcp/tools/glob.py tests/unit/test_glob_pattern.py tests/integration/test_search_tools.py
git commit -m "feat(tools): Glob — pattern→find conversion preserving path segments"
```

---

### Task 4.2: Grep — basic + flags + case_insensitive + include

**Files:**
- Create: `remote_mcp/tools/grep.py`
- Modify: `tests/integration/test_search_tools.py`

- [ ] **Step 1: Failing tests**

Append to `tests/integration/test_search_tools.py`:
```python
from remote_mcp.tools import grep as grep_tool


@pytest.fixture
def grep_conn(conn):
    # Use the same setup as glob, plus content files
    conn.exec("rm -rf /tmp/rmcp-grep-test && mkdir -p /tmp/rmcp-grep-test")
    write_tool.write(conn, "/tmp/rmcp-grep-test/a.py",
                     "import os\n\ndef foo():\n    return 42\n")
    write_tool.write(conn, "/tmp/rmcp-grep-test/b.py",
                     "import sys\n\ndef bar():\n    return foo()\n")
    write_tool.write(conn, "/tmp/rmcp-grep-test/c.txt",
                     "FOO is a value\nfoo is something\n")
    return conn


def test_grep_basic(grep_conn):
    out = grep_tool.grep_tool(grep_conn, "foo", "/tmp/rmcp-grep-test")
    # Default is content mode, returns path:lineno:line
    assert "a.py" in out
    assert "def foo" in out
    assert ":3:" in out  # foo defined on line 3


def test_grep_no_match(grep_conn):
    out = grep_tool.grep_tool(grep_conn, "nonexistent_keyword_xyz", "/tmp/rmcp-grep-test")
    assert out == "No matches found"


def test_grep_case_insensitive(grep_conn):
    out = grep_tool.grep_tool(
        grep_conn, "foo", "/tmp/rmcp-grep-test", case_insensitive=True
    )
    assert "FOO is a value" in out
    assert "foo is something" in out


def test_grep_include_filter(grep_conn):
    out = grep_tool.grep_tool(
        grep_conn, "foo", "/tmp/rmcp-grep-test", include="*.py"
    )
    assert "a.py" in out
    assert "b.py" in out
    assert "c.txt" not in out
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_search_tools.py -v -k grep`
Expected: FAIL.

- [ ] **Step 3: Implement (basic — no context yet)**

`remote_mcp/tools/grep.py`:
```python
"""Grep tool. See spec §5.3.9."""
import shlex

from ..connection import SSHConnection


_VALID_OUTPUT_MODES = ("content", "files_with_matches", "count")


def grep_tool(conn: SSHConnection, pattern: str, path: str,
              include: str = "",
              case_insensitive: bool = False,
              before: int = 0,
              after: int = 0,
              context: int = 0,
              head_limit: int = 200,
              output_mode: str = "content") -> str:
    if output_mode not in _VALID_OUTPUT_MODES:
        return (
            f"Error: invalid output_mode: {output_mode!r}. "
            f"Must be one of {_VALID_OUTPUT_MODES}."
        )

    if output_mode == "content":
        mode_flag = "-n"
    elif output_mode == "files_with_matches":
        mode_flag = "-l"
    else:
        mode_flag = "-c"

    flags = ["-r", mode_flag]
    if case_insensitive:
        flags.append("-i")

    if output_mode == "content":
        if context > 0:
            flags.append(f"-C{context}")
        else:
            if before > 0:
                flags.append(f"-B{before}")
            if after > 0:
                flags.append(f"-A{after}")

    include_opt = f"--include={shlex.quote(include)}" if include else ""

    cmd = (
        f"grep {' '.join(flags)} {include_opt} -E "
        f"{shlex.quote(pattern)} {shlex.quote(path)} "
        f"| head -{head_limit}"
    )
    result = conn.exec(cmd)
    if result.exit_code == 2:
        return f"Error: {result.stderr.strip()}"
    if result.exit_code == 1 or not result.stdout.strip():
        return "No matches found"
    return result.stdout
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_search_tools.py -v -k grep`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/grep.py tests/integration/test_search_tools.py
git commit -m "feat(tools): Grep — basic + case_insensitive + include filter"
```

---

### Task 4.3: Grep — context, output_mode, head_limit

**Files:**
- Modify: `tests/integration/test_search_tools.py`

The implementation already supports these (Task 4.2); this task adds the integration tests verifying each parameter.

- [ ] **Step 1: Add tests**

Append:
```python
def test_grep_context_C(grep_conn):
    # With -C 1, matching "def foo" should include line above and below
    out = grep_tool.grep_tool(
        grep_conn, "def foo", "/tmp/rmcp-grep-test", context=1, include="*.py"
    )
    # Expect to see the blank line above and "return 42" below
    assert "def foo" in out
    assert "return 42" in out


def test_grep_output_mode_files_with_matches(grep_conn):
    out = grep_tool.grep_tool(
        grep_conn, "foo", "/tmp/rmcp-grep-test",
        output_mode="files_with_matches"
    )
    lines = [l for l in out.splitlines() if l.strip()]
    # Each line is a path; no `:` content separators per line (just full paths)
    for ln in lines:
        # Should be a path without ":<lineno>:<content>"
        assert ln.count(":") == 0 or ln.startswith("/tmp/")


def test_grep_output_mode_count(grep_conn):
    out = grep_tool.grep_tool(
        grep_conn, "foo", "/tmp/rmcp-grep-test", output_mode="count"
    )
    # Each line: path:count
    for ln in out.splitlines():
        if ln.strip():
            assert ":" in ln
            count_str = ln.rsplit(":", 1)[1].strip()
            assert count_str.isdigit()


def test_grep_head_limit(grep_conn):
    # Write a file with many matching lines
    body = "\n".join(["match_xyz"] * 50) + "\n"
    write_tool.write(grep_conn, "/tmp/rmcp-grep-test/many.txt", body)
    out = grep_tool.grep_tool(
        grep_conn, "match_xyz", "/tmp/rmcp-grep-test", head_limit=10
    )
    # Output should have at most 10 lines
    non_empty = [l for l in out.splitlines() if l.strip()]
    assert len(non_empty) <= 10


def test_grep_invalid_output_mode(grep_conn):
    out = grep_tool.grep_tool(
        grep_conn, "foo", "/tmp/rmcp-grep-test", output_mode="bogus"
    )
    assert out.startswith("Error: invalid output_mode")
```

- [ ] **Step 2: Run, all PASS**

Run: `pytest tests/integration/test_search_tools.py -v -k grep`
Expected: All grep tests PASS (4 from Task 4.2 + 5 new = 9).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_search_tools.py
git commit -m "test(tools): Grep context, output_mode variants, head_limit"
```

---

## Stage 5: Server + Bash + Feedback

References: spec §5.3.7 (Bash), §5.3.10 (Feedback), §5.4 (server.py), §6 (schemas).

### Task 5.1: `schemas.py` — JSON schemas for all 10 tools

**Files:**
- Create: `remote_mcp/schemas.py`
- Create: `tests/unit/test_schemas.py`

- [ ] **Step 1: Failing tests**

`tests/unit/test_schemas.py`:
```python
import json
from remote_mcp.schemas import ALL_TOOL_SCHEMAS


def test_all_ten_tools_have_schemas():
    expected = {
        "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
        "Bash", "Glob", "Grep", "Feedback",
    }
    assert set(ALL_TOOL_SCHEMAS.keys()) == expected


def test_each_schema_has_required_keys():
    for name, schema in ALL_TOOL_SCHEMAS.items():
        assert "type" in schema, name
        assert schema["type"] == "object"
        assert "properties" in schema, name


def test_required_lists_are_correct():
    assert "file_path" in ALL_TOOL_SCHEMAS["Read"]["required"]
    assert set(ALL_TOOL_SCHEMAS["Edit"]["required"]) == {"file_path", "old_string", "new_string"}
    assert "command" in ALL_TOOL_SCHEMAS["Bash"]["required"]
    assert set(ALL_TOOL_SCHEMAS["Feedback"]["required"]) == {"category", "summary"}


def test_schemas_are_json_serializable():
    for name, schema in ALL_TOOL_SCHEMAS.items():
        json.dumps(schema)  # must not raise
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_schemas.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `remote_mcp/schemas.py`**

```python
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
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/unit/test_schemas.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/schemas.py tests/unit/test_schemas.py
git commit -m "feat(schemas): JSON schemas + descriptions for all 10 tools"
```

---

### Task 5.2: Bash tool — foreground

**Files:**
- Create: `remote_mcp/tools/bash.py`
- Create: `tests/integration/test_bash_tool.py`

- [ ] **Step 1: Failing tests**

`tests/integration/test_bash_tool.py`:
```python
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import bash as bash_tool


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        bash_timeout_default=15,
    )
    c = SSHConnection(cfg)
    c.connect()
    yield c
    c.close()


def test_bash_foreground_echo(conn):
    out = bash_tool.bash(conn, "echo hi")
    assert "[host=test cwd=" in out
    assert "hi" in out


def test_bash_foreground_persists_cwd(conn):
    bash_tool.bash(conn, "cd /tmp")
    out = bash_tool.bash(conn, "pwd")
    assert "cwd=/tmp" in out
    assert "/tmp" in out


def test_bash_foreground_nonzero_exit(conn):
    out = bash_tool.bash(conn, "false")
    assert "[Exit code: 1]" in out


def test_bash_foreground_output_cap(conn):
    conn.config.bash_output_cap = 200
    out = bash_tool.bash(conn, "yes hello | head -1000")
    # Total length should be bounded by cap + truncation message
    assert "[truncated to" in out


def test_bash_foreground_timeout(conn):
    out = bash_tool.bash(conn, "sleep 100", timeout=2)
    assert out.startswith("Error: Command timed out")
    assert "on test" in out
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_bash_tool.py -v -k foreground`
Expected: FAIL.

- [ ] **Step 3: Implement (foreground branch only — background in next task)**

`remote_mcp/tools/bash.py`:
```python
"""Bash tool. See spec §5.3.7."""
import re
import shlex
import uuid

from ..connection import SSHConnection


def bash(conn: SSHConnection, command: str,
         run_in_background: bool = False,
         timeout: float = None,
         description: str = "") -> str:
    if timeout is None:
        timeout = float(conn.config.bash_timeout_default)
    if run_in_background:
        return _bash_background(conn, command)
    return _bash_foreground(conn, command, timeout)


def _bash_foreground(conn: SSHConnection, command: str, timeout: float) -> str:
    session = conn.get_bash_session()
    try:
        result = session.execute(command, timeout=timeout)
    except TimeoutError:
        return f"Error: Command timed out after {timeout}s on {conn.config.name}"

    cwd = session.current_cwd()
    output = result.output

    prefix = f"[host={conn.config.name} cwd={cwd}]\n"

    if result.exit_code != 0:
        output += f"\n[Exit code: {result.exit_code}]"

    cap = conn.config.bash_output_cap
    if len(output) > cap:
        output = output[:cap] + f"\n... [truncated to {cap} bytes]"

    return prefix + output


def _bash_background(conn: SSHConnection, command: str) -> str:
    # Placeholder; implemented in Task 5.3
    raise NotImplementedError("run_in_background implemented in next task")
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_bash_tool.py -v -k foreground`
Expected: 5 tests PASS (timeout test takes ~2s).

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/bash.py tests/integration/test_bash_tool.py
git commit -m "feat(tools): Bash foreground — host+cwd prefix, exit code, output cap, timeout"
```

---

### Task 5.3: Bash tool — `run_in_background` with `setsid`

**Files:**
- Modify: `remote_mcp/tools/bash.py`
- Modify: `tests/integration/test_bash_tool.py`

- [ ] **Step 1: Failing tests**

Append to `tests/integration/test_bash_tool.py`:
```python
import re
import time


def test_bash_background_returns_pid_and_log(conn):
    out = bash_tool.bash(conn, "sleep 30", run_in_background=True)
    assert "Started background task" in out
    assert re.search(r"PID:\s*\d+", out)
    assert re.search(r"Log:\s*/tmp/rmcp-bg-[a-f0-9]+\.log", out)
    # Cleanup
    m = re.search(r"PID:\s*(\d+)", out)
    pid = m.group(1)
    bash_tool.bash(conn, f"kill -KILL -- -{pid} 2>/dev/null; true")


def test_bash_background_kill_via_process_group(conn):
    out = bash_tool.bash(conn, "sleep 100", run_in_background=True)
    m = re.search(r"PID:\s*(\d+)", out)
    pid = m.group(1)

    # Verify alive
    alive = bash_tool.bash(conn, f"kill -0 {pid} && echo running || echo done")
    assert "running" in alive

    # Kill the whole group
    bash_tool.bash(conn, f"kill -TERM -- -{pid}")
    time.sleep(1.5)

    dead = bash_tool.bash(conn, f"kill -0 {pid} 2>/dev/null && echo running || echo done")
    assert "done" in dead


def test_bash_background_kills_children_via_group(conn):
    """Verify -PGID kill takes down spawned children."""
    cmd = "( sleep 200 & sleep 300 & wait )"
    out = bash_tool.bash(conn, cmd, run_in_background=True)
    m = re.search(r"PID:\s*(\d+)", out)
    pid = m.group(1)
    time.sleep(0.5)

    # There should be sleep processes alive
    sleeps_alive = bash_tool.bash(conn, "pgrep -c '^sleep$' || echo 0")
    n = int(re.search(r"\d+", sleeps_alive.splitlines()[-1]).group())
    assert n >= 2

    bash_tool.bash(conn, f"kill -KILL -- -{pid}")
    time.sleep(1.5)

    sleeps_after = bash_tool.bash(conn, "pgrep -c '^sleep$' || echo 0")
    n_after = int(re.search(r"\d+", sleeps_after.splitlines()[-1]).group())
    assert n_after == 0


def test_bash_background_log_readable(conn):
    out = bash_tool.bash(
        conn, "for i in 1 2 3; do echo line$i; sleep 0.1; done",
        run_in_background=True,
    )
    log_match = re.search(r"Log:\s*(/tmp/rmcp-bg-[a-f0-9]+\.log)", out)
    log_path = log_match.group(1)
    time.sleep(1.5)
    # Read the log via Bash cat
    log_content = bash_tool.bash(conn, f"cat {log_path}")
    assert "line1" in log_content
    assert "line2" in log_content
    assert "line3" in log_content
```

- [ ] **Step 2: Run, FAIL (NotImplementedError)**

Run: `pytest tests/integration/test_bash_tool.py -v -k background`
Expected: FAIL with NotImplementedError.

- [ ] **Step 3: Implement `_bash_background()`**

Replace the placeholder `_bash_background` in `remote_mcp/tools/bash.py`:

```python
def _bash_background(conn: SSHConnection, command: str) -> str:
    """
    Start command as a background process group leader.
    See spec §5.3.7 — setsid is non-optional.
    """
    session = conn.get_bash_session()
    bg_uuid = uuid.uuid4().hex[:12]
    log_path = f"/tmp/rmcp-bg-{bg_uuid}.log"
    quoted_cmd = shlex.quote(command)
    quoted_log = shlex.quote(log_path)

    # setsid: creates new session, the bash becomes session/group leader (PID = PGID)
    # nohup: belt-and-suspenders against SIGHUP
    # </dev/null: detach stdin
    # ( ... & echo "BG_PID=$!" ): subshell so $! is the bg PID
    wrap = (
        f"( setsid nohup bash -c {quoted_cmd} "
        f"> {quoted_log} 2>&1 </dev/null & echo \"BG_PID=$!\" )"
    )
    try:
        result = session.execute(wrap, timeout=10.0)
    except TimeoutError:
        return f"Error: failed to launch background task on {conn.config.name} (timeout)"

    m = re.search(r"BG_PID=(\d+)", result.output)
    if not m:
        return (
            f"Error: failed to start background task on {conn.config.name}. "
            f"Output: {result.output[:500]}"
        )
    pid = m.group(1)
    cwd = session.current_cwd()

    return (
        f"[host={conn.config.name} cwd={cwd}]\n"
        f"Started background task.\n"
        f"  PID: {pid}\n"
        f"  Log: {log_path}\n\n"
        f"To check status:    Bash(\"kill -0 {pid} && echo running || echo done\")\n"
        f"To read new output: Read(\"{log_path}\", offset=<last_line+1>)\n"
        f"To stop gracefully: Bash(\"kill -TERM -- -{pid}\")\n"
        f"To force stop:      Bash(\"kill -KILL -- -{pid}\")\n"
    )
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_bash_tool.py -v -k background`
Expected: 4 tests PASS (each takes a few seconds).

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/bash.py tests/integration/test_bash_tool.py
git commit -m "feat(tools): Bash run_in_background — setsid process group + PID return"
```

---

### Task 5.4: Feedback tool

**Files:**
- Create: `remote_mcp/tools/feedback.py`
- Create: `tests/unit/test_feedback_logic.py`
- Create: `tests/integration/test_feedback_tool.py`

- [ ] **Step 1: Unit tests for pure logic**

`tests/unit/test_feedback_logic.py`:
```python
import json
from pathlib import Path

from remote_mcp.tools.feedback import feedback


class _FakeConfig:
    def __init__(self, name, feedback_path):
        self.name = name
        # feedback expects conn.config.name and resolves feedback_path separately
        self.feedback_path = feedback_path


class _FakeConn:
    def __init__(self, name, feedback_path):
        self.config = _FakeConfig(name, feedback_path)


def test_feedback_writes_jsonl_entry(tmp_path: Path):
    fpath = tmp_path / "fb.jsonl"
    conn = _FakeConn("prod", str(fpath))
    out = feedback(conn, str(fpath), "bug", "Glob ** broke", "details here")
    assert out.startswith("Feedback recorded: [bug] Glob ** broke")

    lines = fpath.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["category"] == "bug"
    assert entry["summary"] == "Glob ** broke"
    assert entry["details"] == "details here"
    assert entry["host"] == "prod"
    assert "ts" in entry
    assert "session_pid" in entry


def test_feedback_creates_parent_dir(tmp_path: Path):
    fpath = tmp_path / "sub" / "dirs" / "fb.jsonl"
    conn = _FakeConn("h", str(fpath))
    feedback(conn, str(fpath), "enhancement", "Add X")
    assert fpath.exists()


def test_feedback_rejects_invalid_category(tmp_path: Path):
    fpath = tmp_path / "fb.jsonl"
    conn = _FakeConn("h", str(fpath))
    out = feedback(conn, str(fpath), "wishlist", "x")
    assert out.startswith("Error: category must be")
    # File must not be created
    assert not fpath.exists()


def test_feedback_rejects_empty_summary(tmp_path: Path):
    fpath = tmp_path / "fb.jsonl"
    conn = _FakeConn("h", str(fpath))
    out = feedback(conn, str(fpath), "bug", "")
    assert out == "Error: summary cannot be empty"
    assert not fpath.exists()


def test_feedback_concurrent_appends_atomic(tmp_path: Path):
    """Simulate concurrent writes; lines should be intact (no interleaving)."""
    import multiprocessing as mp
    fpath = tmp_path / "fb.jsonl"

    def worker(i):
        conn = _FakeConn(f"h{i}", str(fpath))
        for j in range(20):
            feedback(conn, str(fpath), "bug", f"sum-{i}-{j}", "x" * 100)

    procs = [mp.Process(target=worker, args=(i,)) for i in range(4)]
    for p in procs: p.start()
    for p in procs: p.join()

    lines = fpath.read_text().splitlines()
    assert len(lines) == 80
    for ln in lines:
        json.loads(ln)  # each is valid JSON
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_feedback_logic.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`remote_mcp/tools/feedback.py`:
```python
"""Feedback tool. See spec §5.3.10."""
import json
import os
import pathlib
from datetime import datetime, timezone


def feedback(conn, feedback_path: str,
             category: str, summary: str, details: str = "") -> str:
    if category not in ("bug", "enhancement"):
        return (
            f"Error: category must be 'bug' or 'enhancement', got {category!r}"
        )
    if not summary.strip():
        return "Error: summary cannot be empty"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": conn.config.name,
        "category": category,
        "summary": summary.strip(),
        "details": (details.strip() or None) if details else None,
        "session_pid": os.getpid(),
    }

    path = pathlib.Path(feedback_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    # JSONL append. Single write() of < PIPE_BUF (~4 KB on Linux) is POSIX-atomic
    # → multi-process append safe.
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)

    return f"Feedback recorded: [{category}] {summary} -> {feedback_path}"
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/unit/test_feedback_logic.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/feedback.py tests/unit/test_feedback_logic.py
git commit -m "feat(tools): Feedback — local JSONL append with POSIX-atomic concurrency"
```

---

### Task 5.5: `server.py` — MCP app + call_tool dispatch + reconnect WARNING

**Files:**
- Create: `remote_mcp/server.py`
- Create: `tests/integration/test_server.py`

- [ ] **Step 1: Failing test**

`tests/integration/test_server.py`:
```python
import asyncio
import pytest

from remote_mcp.config import HostConfig, RootConfig
from remote_mcp import server as srv


@pytest.fixture
def runtime_config(sshd_container, ssh_key, tmp_path):
    cfg = HostConfig(
        name="test",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    root = RootConfig(
        hosts={"test": cfg},
        default_host="test",
        feedback_path=str(tmp_path / "fb.jsonl"),
    )
    return root


def test_list_tools_returns_ten(runtime_config):
    # Plumb the connection into the global
    srv._init_for_test(runtime_config, "test")
    try:
        tools = asyncio.run(srv.list_tools())
        names = [t.name for t in tools]
        assert set(names) == {
            "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
            "Bash", "Glob", "Grep", "Feedback",
        }
    finally:
        srv._teardown_for_test()


def test_call_tool_dispatches_read(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        # Write a file first
        result = asyncio.run(srv.call_tool("Write", {
            "file_path": "/tmp/rmcp-srv-test.txt",
            "content": "hi\n",
        }))
        assert "Successfully wrote" in result[0].text

        result = asyncio.run(srv.call_tool("Read", {
            "file_path": "/tmp/rmcp-srv-test.txt",
        }))
        assert "     1\thi" in result[0].text
    finally:
        srv._teardown_for_test()


def test_call_tool_reconnect_warning(runtime_config, sshd_kill_and_restart):
    srv._init_for_test(runtime_config, "test")
    try:
        # First call succeeds
        asyncio.run(srv.call_tool("Bash", {"command": "echo a"}))
        # Kill sshd; next call triggers reconnect → WARNING
        sshd_kill_and_restart()
        # Use exec_with_retry-backed path; we call a tool that ultimately uses exec
        # Trigger reconnect by manually flagging since persistent bash session needs to
        # see the dead transport on its NEXT execute() call.
        # Simplest: just call Glob which uses exec() and will fail+retry.
        result = asyncio.run(srv.call_tool("Glob", {
            "pattern": "*", "path": "/tmp",
        }))
        text = result[0].text
        assert "[WARNING] SSH connection to test was lost" in text
    finally:
        srv._teardown_for_test()
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_server.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `remote_mcp/server.py`**

```python
"""MCP server: list_tools, call_tool, dispatch, reconnect WARNING. See spec §5.4."""
import asyncio
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import RootConfig, load_config
from .connection import SSHConnection
from .schemas import ALL_TOOL_SCHEMAS, ALL_TOOL_DESCRIPTIONS

from .tools import bash as bash_tool
from .tools import edit as edit_tool
from .tools import feedback as feedback_tool
from .tools import file_stat as file_stat_tool
from .tools import glob as glob_tool
from .tools import grep as grep_tool
from .tools import multi_edit as multi_edit_tool
from .tools import multi_read as multi_read_tool
from .tools import read as read_tool
from .tools import write as write_tool


app = Server("remote-mcp")

# Module globals — set by main() before stdio loop starts.
# These are intentionally simple to keep dispatch unambiguous; spec §5.4
# documents this 'global conn' pattern.
_conn: Optional[SSHConnection] = None
_root_config: Optional[RootConfig] = None


@app.list_tools()
async def list_tools():
    return [
        Tool(name=name,
             description=ALL_TOOL_DESCRIPTIONS[name],
             inputSchema=ALL_TOOL_SCHEMAS[name])
        for name in ALL_TOOL_SCHEMAS
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    global _conn, _root_config

    # ALL tools dispatch through _with_retry per spec §9: on SSH drop,
    # auto-reconnect once then retry the operation. Feedback is the one
    # exception — it doesn't touch SSH, so retry is no-op but harmless.
    result = _with_retry(lambda: _raw_dispatch(name, arguments))

    # Check reconnect flag AFTER the call (it may have been set by the retry path).
    prefix = ""
    if _conn is not None and _conn.check_and_clear_reconnect_flag():
        prefix = (
            f"[WARNING] SSH connection to {_conn.config.name} was lost and "
            f"has been re-established. The remote bash session has been reset: "
            f"working directory is now $HOME, all environment variables set in "
            f"previous commands are lost. Use absolute paths and re-run any "
            f"necessary setup commands.\n\n"
        )
    return [TextContent(type="text", text=prefix + result)]


def _raw_dispatch(name: str, args: dict) -> str:
    """Pure dispatch with no retry logic — wrapped by _with_retry above."""
    if name == "Read":
        return read_tool.read(_conn, **args)
    if name == "Write":
        return write_tool.write(_conn, **args)
    if name == "Edit":
        return edit_tool.edit(_conn, **args)
    if name == "MultiEdit":
        return multi_edit_tool.multi_edit(_conn, **args)
    if name == "MultiRead":
        return multi_read_tool.multi_read(_conn, **args)
    if name == "FileStat":
        return file_stat_tool.file_stat(_conn, **args)
    if name == "Bash":
        return bash_tool.bash(_conn, **args)
    if name == "Glob":
        return glob_tool.glob_tool(_conn, **args)
    if name == "Grep":
        return grep_tool.grep_tool(_conn, **args)
    if name == "Feedback":
        return feedback_tool.feedback(
            _conn, _root_config.feedback_path, **args
        )
    return f"Error: unknown tool: {name}"


def _with_retry(call):
    """
    Run `call`; on SSH-level failure, reconnect once then retry.
    Per spec §9 — auto-reconnect once; reconnect failure returns Error string
    (caller does NOT see WARNING for failed reconnect).
    """
    import paramiko
    try:
        return call()
    except (paramiko.SSHException, EOFError, OSError) as e:
        try:
            _conn._do_reconnect()
        except Exception as e2:
            return (
                f"Error: SSH connection to {_conn.config.name} lost and "
                f"reconnect failed: {e2}"
            )
        # Reconnect succeeded; _do_reconnect set _reconnected=True so the WARNING
        # prefix will be applied by call_tool after this returns.
        try:
            return call()
        except Exception as e3:
            return f"Error: {e3}"


async def main(host_name: str, config_path: str) -> None:
    global _conn, _root_config
    _root_config = load_config(config_path)
    host_cfg = _root_config.hosts[host_name]
    jump_cfg = None
    if host_cfg.jump_host:
        jump_cfg = _root_config.hosts[host_cfg.jump_host]
    _conn = SSHConnection(host_cfg, jump_config=jump_cfg)
    _conn.connect()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream,
                app.create_initialization_options(),
            )
    finally:
        _conn.close()


# ---- Test helpers (no stdio loop) ----

def _init_for_test(root: RootConfig, host_name: str) -> None:
    """Connect for tests without entering stdio loop."""
    global _conn, _root_config
    _root_config = root
    host_cfg = root.hosts[host_name]
    jump_cfg = root.hosts.get(host_cfg.jump_host) if host_cfg.jump_host else None
    _conn = SSHConnection(host_cfg, jump_config=jump_cfg)
    _conn.connect()


def _teardown_for_test() -> None:
    global _conn, _root_config
    if _conn is not None:
        _conn.close()
    _conn = None
    _root_config = None
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_server.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/server.py tests/integration/test_server.py
git commit -m "feat(server): MCP app, list_tools, call_tool dispatch with reconnect WARNING"
```

---

## Stage 6: Polish & Documentation

### Task 6.1: `__main__.py` — CLI entry point

**Files:**
- Create: `remote_mcp/__main__.py`

- [ ] **Step 1: Write the file**

`remote_mcp/__main__.py`:
```python
"""CLI entry point: python -m remote_mcp --host <name>"""
import argparse
import asyncio
import sys

from .server import main as server_main


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="remote-mcp",
        description="MCP server proxying tools to a remote Linux host over SSH",
    )
    parser.add_argument(
        "--host", required=True,
        help="Host name from config.yaml to connect to",
    )
    parser.add_argument(
        "--config", default="~/.config/remote-mcp/config.yaml",
        help="Path to config.yaml (default: ~/.config/remote-mcp/config.yaml)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Connect, smoke-test, then exit (no stdio loop)",
    )
    args = parser.parse_args()

    if args.test:
        from .config import load_config
        from .connection import SSHConnection
        root = load_config(args.config)
        host_cfg = root.hosts[args.host]
        jump_cfg = root.hosts.get(host_cfg.jump_host) if host_cfg.jump_host else None
        conn = SSHConnection(host_cfg, jump_config=jump_cfg)
        conn.connect()
        try:
            r = conn.exec("echo OK")
            if r.stdout.strip() == "OK":
                print(f"Connected to {args.host} ({host_cfg.user}@{host_cfg.hostname}). All tools: OK")
                sys.exit(0)
            else:
                print(f"Connected but echo failed: {r.stdout!r}")
                sys.exit(1)
        finally:
            conn.close()

    asyncio.run(server_main(args.host, args.config))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Smoke test (with a real config)**

Create a temporary config and run `--test`:
```bash
mkdir -p ~/.config/remote-mcp
cat > /tmp/rmcp-smoke-config.yaml <<EOF
hosts:
  test:
    hostname: 127.0.0.1
    user: $USER
    port: 22
EOF
# This will only work if you have local SSH set up. Otherwise skip and rely on integration tests.
# python -m remote_mcp --host test --config /tmp/rmcp-smoke-config.yaml --test
```

For now, just verify the script can be invoked:
```bash
python -m remote_mcp --help
```
Expected: argparse help printed.

- [ ] **Step 3: Commit**

```bash
git add remote_mcp/__main__.py
git commit -m "feat(cli): __main__.py with --host, --config, --test args"
```

---

### Task 6.2: `CLAUDE.md.fragment.md` (M2 — user workflow guide)

**Files:**
- Create: `CLAUDE.md.fragment.md` (repo root)

- [ ] **Step 1: Write the file**

Contents per spec §10.2:

`CLAUDE.md.fragment.md`:
```markdown
## 在远程主机上工作（remote-mcp 工具使用指南）

本项目通过 `mcp__remote-<host>__` 系列工具操控远程服务器。SSH 链路带宽有限、延迟较高。
请遵循以下工作流：

### 单主机模式

**查代码 / 探索仓库**
- 查代码先用 Grep 定位关键字。如果需要看上下文，**直接用 Grep 的 `context=5`（或 before/after）一次拿到匹配 + 周围代码**，不要 Grep 后再 Read 跟进。
- 只想知道某个文件存在吗、多大、什么时候改的？**用 FileStat**，不要 Read 试探（可能传输 50MB 只为知道文件不该读）。
- 探索多个相关文件（如 config / models / utils 一组）**一次 MultiRead 调用**，不要连续 Read。

**编辑文件**
- 同一文件多处修改，**一律用 MultiEdit**，禁止连续 Edit。

**Shell 操作**
- 多步骤操作优先组合命令：`cmd1 && cmd2 && cmd3` 一次 Bash 调用。更复杂的逻辑写脚本（Write 上传 → Bash 执行）。
- 长耗时操作（build / 测试 / install / 大下载）**用 `Bash(command="...", run_in_background=true)`**，agent 不会被阻塞。
  - 工具返回会打印 PID、日志路径、4 条操作命令模板——**照抄即可**。
  - 用 `Read(log_path, offset=<last_line+1>)` 增量拉日志，不要 `Bash("cat log")`。
  - 任务做完或确定不要了，**务必用 `Bash("kill -TERM -- -<pid>")` 收尾**。
- 前台 Bash 长操作显式设大 timeout（如 600s）；可能拖到几分钟以上的直接用 `run_in_background`。
- 大输出命令要谨慎：`find /`、`ls -R /`、`grep -r 通用词 /` 会刷爆带宽，先想清楚再发。

### 多主机模式（2-3 台同时操作时）
- 工具调用结果会有 `[host=X cwd=Y]` 前缀，注意辨认当前操作的是哪台主机。
- 尽量把工作集中在单台主机上完成；跨主机协调需求增加错误率。
- 跨主机文件传输：用 Bash 调 `scp <local>:<path> <remote>:<path>`（需用户预先在主机间配好 SSH 互信）。**禁止** Read-本地中转-Write 的"双跳"模式。
- 看到 `[WARNING] SSH connection to <host> was lost` 时，状态丢失仅限那台主机。

### 持续反馈（Continuous improvement feedback）

remote-mcp 提供 `Feedback` 工具，让你（agent）把使用过程中遇到的问题或灵感沉淀下来。

✅ **DO**：
- 某个 remote-mcp 工具的行为不符合 Claude Code 原生工具的预期
- 某个工具有 bug：超时反常、输出损坏、结果与文档不符
- 你想到："如果有 X 工具或 Y 参数会让这件事简单很多"——具体到能描述 API
- 工作流摩擦：某场景需要 3+ 次工具调用才能完成

❌ **DON'T**：
- 用户代码里的 bug（应该改用户代码）
- 远程系统问题（应该写到运维记录里）
- 不基于实际遇到情况的猜测

**调用规范**：
- `category="bug"` 配实际复现描述
- `category="enhancement"` 配具体到能 mock API
- **不打断当前任务**：file 完一条 feedback 就继续手头的事
- summary 一行；details 写背景

**隐私**：写入本地 `~/.local/share/remote-mcp/feedback.jsonl`，不上传任何地方。
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md.fragment.md
git commit -m "docs: add CLAUDE.md.fragment.md (M2 — user workflow guide)"
```

---

### Task 6.3: README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the file**

```markdown
# remote-mcp

A local Python MCP server that proxies file and shell tools to a remote Linux host over SSH. Claude Code (and any other MCP client) gets 10 tools — Read, Write, Edit, MultiEdit, MultiRead, FileStat, Bash, Glob, Grep, Feedback — all operating on the remote.

## Why

Sometimes the code you want Claude Code to work on lives on a remote server, the server has no agent-installable software, and you only have SSH. This bridges that gap.

## Install

```bash
git clone <repo>
cd remote-mcp
pip install -e .
```

## Configure

Create `~/.config/remote-mcp/config.yaml`:

```yaml
hosts:
  prod:
    hostname: 192.168.1.100
    user: ubuntu
    key_path: ~/.ssh/id_ed25519
    keepalive_interval: 30

default_host: prod
feedback_path: ~/.local/share/remote-mcp/feedback.jsonl
```

See the design spec for the full schema (`docs/superpowers/specs/2026-05-26-remote-mcp-design.md` §11).

## Register with Claude Code

```bash
claude mcp add --global remote-prod -- python -m remote_mcp --host prod
```

Restart Claude Code. The 10 tools appear as `mcp__remote-prod__Read`, etc.

## Recommended: Add the workflow guide

Copy `CLAUDE.md.fragment.md` into your remote project's CLAUDE.md so the agent uses the bandwidth-aware patterns (Grep with context, MultiRead, FileStat, background Bash).

## Smoke test

```bash
python -m remote_mcp --host prod --test
# Expected: Connected to prod (...). All tools: OK
```

## Limitations

See spec §14. Briefly: no TTY commands, text files only, ~3 hosts at a time, Glob `**` is approximate.

## Architecture summary

- 1 Python process per remote host (long-lived, per Claude Code session)
- 1 paramiko Transport per process (compress=on, keepalive=30s)
- Persistent bash channel (sentinel protocol + cwd capture)
- Lazy SFTP for file ops and metadata
- Auto-reconnect once on drop; agent is warned via `[WARNING]` prefix
- Background Bash uses `setsid` for clean process-group kill

Full design: `docs/superpowers/specs/2026-05-26-remote-mcp-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with install/config/register/usage"
```

---

### Task 6.4: Stage acceptance — full integration run

**Files:** (no new files)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS. Currently ~50+ tests across unit and integration.

Note: Integration tests require Docker and may take ~1-2 minutes.

- [ ] **Step 2: Verify acceptance criteria per spec §13 are met**

Cross-check spec §13 stages 1-5 acceptance items against test names. Every acceptance item should map to a test or a manual verification you've done. If any are missing, add them now.

- [ ] **Step 3: Manual sanity — start the server and connect from Claude Code**

This is the ultimate acceptance: register the server with Claude Code, restart it, verify all 10 `mcp__remote-prod__*` tools appear, and run a smoke flow:
- `Read` an actual file
- `Glob` for `*.py` in a small dir
- `Bash` with `run_in_background=true` for `sleep 5`
- `Feedback` a test entry; verify `~/.local/share/remote-mcp/feedback.jsonl` got it

If anything goes wrong in this final manual test, add a regression test before fixing.

- [ ] **Step 4: Commit (if any fixes were needed)**

```bash
git status
# Commit any final tweaks
```

---

## Coverage Summary

| Spec section | Implemented in |
|--------------|---------------|
| §3 architecture | Task 1.2 (compress), Task 1.6 (reconnect), Task 2.1+ (bash) |
| §5.1 connection.py | Tasks 1.1–1.6 |
| §5.1.1 lifecycle | Task 5.5 (main()) + Task 6.1 (__main__) |
| §5.2 sentinel protocol | Tasks 2.1–2.4 |
| §5.3.1 Read | Task 3.1 |
| §5.3.2 Write | Task 3.2 |
| §5.3.3 Edit | Task 3.3 |
| §5.3.4 MultiEdit | Task 3.4 |
| §5.3.5 MultiRead | Task 3.5 |
| §5.3.6 FileStat | Task 3.6 |
| §5.3.7 Bash | Task 5.2 (fg), Task 5.3 (bg) |
| §5.3.8 Glob | Task 4.1 |
| §5.3.9 Grep | Tasks 4.2, 4.3 |
| §5.3.10 Feedback | Task 5.4 |
| §5.4 server.py | Task 5.5 |
| §6 interface table | Task 5.1 (schemas) |
| §7 bandwidth opts | distributed across tool tasks |
| §8 multi-host (P1+P2) | Task 5.2 (Bash prefix), Task 5.5 (WARNING with host) |
| §9 error/reconnect | Tasks 1.6, 5.5 |
| §10.1 M1 descriptions | Task 5.1 |
| §10.2 M2 fragment | Task 6.2 |
| §11 config | Task 1.1 |
| §13 acceptance | Task 6.4 (full sweep) |
| §14 limitations | documented; not implemented (by design) |
| §15 future work | not in scope |

## Execution Notes

- **Frequent commits**: each task ends with a commit. Don't batch.
- **Order matters**: stages are sequential. Stage 2 depends on Stage 1; Stage 3 depends on Stages 1+2; etc. Don't skip ahead.
- **The sshd container fixture is foundational**: if it doesn't work, fix that before anything else.
- **Persistent bash session is the highest risk**: spec §13 stage 2 explicitly suggests building a standalone test script before integrating. The plan's Stage 2 tasks (especially 2.3) embody this — get them rock solid before moving on.
- **Don't add to scope**: §14 limitations are deliberate. §15 future work is for after v1 ships. If a limitation bites during testing, file a Feedback entry — that's exactly the dev-loop the Feedback tool is for.
