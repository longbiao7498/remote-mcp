# Upload / Download / RemoteInfo Implementation Plan (v0.1.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three tools to v0.1.1 — `Upload` (local → remote SFTP put), `Download` (remote → local SFTP get), `RemoteInfo` (report HostConfig identity, VPN-safe).

**Architecture:** Upload/Download wrap paramiko's `sftp.put()` / `sftp.get()` with a preflight size check (`transfer_size_cap`, default 100 MB) and clear failure modes. Tool descriptions explicitly steer Linux/macOS users toward `Bash("scp ...", run_in_background=true)` because scp is non-blocking and supports any size — Upload/Download are a Windows convenience. `RemoteInfo` reads from `conn.config` and returns a structured 5-field summary; it issues NO SSH call (VPN-safe: the IP we connect to is reported, not whatever the remote thinks it is).

**Tech Stack:** Python 3.8+, paramiko (already a dep), pytest + the real-host fixture at `tests/integration/conftest.py` (penglin_lb@192.168.10.20).

---

## Files touched

```
remote_mcp/
├── config.py                  Modify: add transfer_size_cap field to HostConfig (default 100 MB)
├── schemas.py                 Modify: add UPLOAD_SCHEMA, DOWNLOAD_SCHEMA, REMOTEINFO_SCHEMA + DESC + register in ALL_TOOL_SCHEMAS/DESCRIPTIONS
├── server.py                  Modify: import 3 new tool modules; add 3 dispatch arms in _raw_dispatch
└── tools/
    ├── upload.py              Create: sftp.put() with preflight checks
    ├── download.py            Create: sftp.get() with preflight checks
    └── remote_info.py         Create: format conn.config as key=value lines

tests/
├── unit/
│   ├── test_remote_info.py    Create: pure-logic format test (fake conn)
│   └── test_schemas.py        Modify: assert 13 tools (was 10)
└── integration/
    └── test_transfer_tools.py Create: Upload/Download integration tests

docs/
├── reference/
│   ├── README.md              Modify: add 3 tool rows (en + zh)
│   ├── README.zh.md
│   ├── config-schema.md       Modify: document transfer_size_cap (en + zh)
│   ├── config-schema.zh.md
│   ├── errors.md              Modify: catalog new error strings (en + zh)
│   ├── errors.zh.md
│   └── tools/
│       ├── upload.md          Create (en + zh)
│       ├── upload.zh.md
│       ├── download.md
│       ├── download.zh.md
│       ├── remote-info.md
│       └── remote-info.zh.md
└── (CLAUDE.md.fragment / CHANGELOG updates handled in final task)

CLAUDE.md.fragment.md         Modify: add "prefer Bash+scp" rule (en + zh)
CLAUDE.md.fragment.zh.md
CHANGELOG.md                  Modify: [Unreleased] gets v0.1.1 features (en + zh)
CHANGELOG.zh.md
```

---

## Task 1: Add `transfer_size_cap` to HostConfig

**Files:**
- Modify: `remote_mcp/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_config.py`:

```python
def test_load_minimal_config_has_transfer_size_cap_default(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        hosts:
          prod:
            hostname: 10.0.0.1
            user: ubuntu
        default_host: prod
    """).strip())
    root = load_config(str(cfg))
    # Default 100 MB
    assert root.hosts["prod"].transfer_size_cap == 100 * 1024 * 1024


def test_load_config_with_custom_transfer_size_cap(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        hosts:
          big:
            hostname: 10.0.0.2
            user: alice
            transfer_size_cap: 524288000   # 500 MB
    """).strip())
    root = load_config(str(cfg))
    assert root.hosts["big"].transfer_size_cap == 524288000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py::test_load_minimal_config_has_transfer_size_cap_default tests/unit/test_config.py::test_load_config_with_custom_transfer_size_cap -v`
Expected: FAIL with `AttributeError: 'HostConfig' object has no attribute 'transfer_size_cap'`.

- [ ] **Step 3: Add the field to `HostConfig`**

In `remote_mcp/config.py`, add a single line inside the `HostConfig` dataclass (alongside the other tunable fields, after `bash_output_cap`):

```python
    transfer_size_cap: int = 100 * 1024 * 1024   # 100 MB cap for Upload/Download
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/unit/test_config.py -v`
Expected: All config tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/config.py tests/unit/test_config.py
git commit -m "feat(config): add transfer_size_cap (default 100 MB) for Upload/Download"
```

---

## Task 2: Upload tool

**Files:**
- Create: `remote_mcp/tools/upload.py`
- Create: `tests/integration/test_transfer_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_transfer_tools.py`:

```python
"""Integration tests for Upload + Download + RemoteInfo."""
import os
import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import upload as upload_tool


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


def test_upload_small_text_file(conn, tmp_path):
    local = tmp_path / "hello.txt"
    local.write_text("hello upload\n")
    out = upload_tool.upload(conn, str(local), "/tmp/rmcp-upload-1.txt")
    assert out.startswith("Successfully uploaded")
    assert "13 bytes" in out
    # Verify on remote
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-upload-1.txt", "r") as f:
        assert f.read().decode() == "hello upload\n"


def test_upload_binary_file(conn, tmp_path):
    local = tmp_path / "blob.bin"
    raw = bytes(range(256)) * 4   # 1024 bytes including NULs
    local.write_bytes(raw)
    out = upload_tool.upload(conn, str(local), "/tmp/rmcp-upload-bin.bin")
    assert "1024 bytes" in out
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-upload-bin.bin", "rb") as f:
        assert f.read() == raw


def test_upload_local_not_found(conn):
    out = upload_tool.upload(conn, "/tmp/this-does-not-exist-xyz", "/tmp/whatever")
    assert out.startswith("Error: Local file not found:")
    assert "/tmp/this-does-not-exist-xyz" in out


def test_upload_local_is_directory(conn, tmp_path):
    out = upload_tool.upload(conn, str(tmp_path), "/tmp/whatever")
    assert out.startswith("Error: Local path is a directory")


def test_upload_exceeds_size_cap(conn, tmp_path):
    # Set cap small, write file larger than cap
    conn.config.transfer_size_cap = 1024   # 1 KB
    local = tmp_path / "too-big.bin"
    local.write_bytes(b"x" * 2048)   # 2 KB
    out = upload_tool.upload(conn, str(local), "/tmp/rmcp-upload-too-big.bin")
    assert out.startswith("Error: File too large for Upload:")
    assert "2048 bytes" in out
    assert "1024 bytes" in out
    # Error message must guide to scp+background
    assert "scp" in out
    assert "run_in_background=true" in out


def test_upload_remote_permission_denied(conn, tmp_path):
    local = tmp_path / "x.txt"
    local.write_text("x")
    # /etc requires root
    out = upload_tool.upload(conn, str(local), "/etc/rmcp-cannot-write.txt")
    assert out.startswith("Error: Permission denied:")
    assert "/etc/rmcp-cannot-write.txt" in out
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_transfer_tools.py -v -k upload`
Expected: FAIL — `ModuleNotFoundError: No module named 'remote_mcp.tools.upload'`.

- [ ] **Step 3: Implement `remote_mcp/tools/upload.py`**

```python
"""Upload tool. Push a local file to the remote via SFTP.

For Linux/macOS users: prefer Bash + scp/rsync with run_in_background=true
— non-blocking, no size limit, supports resume. This tool is primarily
for Windows users without scp in PATH.
"""
import errno as _errno
import os
import posixpath
import stat as _stat

from ..connection import SSHConnection


def upload(conn: SSHConnection, local_path: str, remote_path: str) -> str:
    """
    Push a local file to the remote host via SFTP.

    Args:
        conn: established SSHConnection.
        local_path: absolute path on the LOCAL machine (where the MCP
            server runs). `~` is expanded.
        remote_path: absolute path on the remote host. Overwrites if exists.

    Returns:
        `"Successfully uploaded <N> bytes from <local_path> to <remote_path>"` on success.
        `"Error: Local file not found: <local_path>"` if local doesn't exist.
        `"Error: Local path is a directory, not a file: <local_path>"` if local is a dir.
        `"Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). ..."`
            if local file size > conn.config.transfer_size_cap. The error message
            includes a ready-to-paste `Bash("scp ...", run_in_background=true)` template.
        `"Error: Permission denied: <remote_path>"` if remote write is denied.
        `"Error: <message>"` for other SFTP errors.
    """
    local = os.path.expanduser(local_path)

    if not os.path.exists(local):
        return f"Error: Local file not found: {local_path}"
    if os.path.isdir(local):
        return f"Error: Local path is a directory, not a file: {local_path}"

    size = os.path.getsize(local)
    cap = conn.config.transfer_size_cap
    if size > cap:
        scp_template = (
            f"Bash(command=\"scp {local_path} {conn.config.user}@"
            f"{conn.config.hostname}:{remote_path}\", run_in_background=true)"
        )
        return (
            f"Error: File too large for Upload: {size} bytes exceeds "
            f"transfer_size_cap ({cap} bytes). For files this size, the "
            f"right tool is Bash with scp or rsync: {scp_template}. It runs "
            f"in background, handles any size, and supports resume."
        )

    sftp = conn.get_sftp()
    # Ensure parent dir exists on remote (matches Write's behavior)
    parent = posixpath.dirname(remote_path)
    try:
        if parent:
            from .write import _sftp_mkdirs
            _sftp_mkdirs(sftp, parent)
        sftp.put(local, remote_path)
    except PermissionError:
        return f"Error: Permission denied: {remote_path}"
    except (IOError, OSError) as e:
        if getattr(e, "errno", None) == _errno.EACCES:
            return f"Error: Permission denied: {remote_path}"
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"

    return f"Successfully uploaded {size} bytes from {local_path} to {remote_path}"
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_transfer_tools.py -v -k upload`
Expected: All 6 upload tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/upload.py tests/integration/test_transfer_tools.py
git commit -m "feat(tools): Upload — SFTP put with size cap + scp guidance"
```

---

## Task 3: Download tool

**Files:**
- Create: `remote_mcp/tools/download.py`
- Modify: `tests/integration/test_transfer_tools.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/integration/test_transfer_tools.py`:

```python
from remote_mcp.tools import download as download_tool


def test_download_small_text_file(conn, tmp_path):
    # Seed a remote file
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-download-1.txt", "w") as f:
        f.write(b"hello download\n")
    local = tmp_path / "downloaded.txt"
    out = download_tool.download(conn, "/tmp/rmcp-download-1.txt", str(local))
    assert out.startswith("Successfully downloaded")
    assert "15 bytes" in out
    assert local.read_text() == "hello download\n"


def test_download_binary_file(conn, tmp_path):
    sftp = conn.get_sftp()
    raw = bytes(range(256)) * 4
    with sftp.file("/tmp/rmcp-download-bin.bin", "wb") as f:
        f.write(raw)
    local = tmp_path / "blob.bin"
    out = download_tool.download(conn, "/tmp/rmcp-download-bin.bin", str(local))
    assert "1024 bytes" in out
    assert local.read_bytes() == raw


def test_download_remote_not_found(conn, tmp_path):
    local = tmp_path / "x.txt"
    out = download_tool.download(conn, "/tmp/this-does-not-exist-xyz", str(local))
    assert out.startswith("Error: Remote file not found:")
    assert "/tmp/this-does-not-exist-xyz" in out


def test_download_exceeds_size_cap(conn, tmp_path):
    conn.config.transfer_size_cap = 1024
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-download-too-big.bin", "wb") as f:
        f.write(b"y" * 2048)
    local = tmp_path / "out.bin"
    out = download_tool.download(conn, "/tmp/rmcp-download-too-big.bin", str(local))
    assert out.startswith("Error: File too large for Download:")
    assert "2048 bytes" in out
    assert "1024 bytes" in out
    assert "scp" in out
    assert "run_in_background=true" in out
    # Local must NOT have been created
    assert not local.exists()
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/integration/test_transfer_tools.py -v -k download`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `remote_mcp/tools/download.py`**

```python
"""Download tool. Pull a remote file to local via SFTP.

For Linux/macOS users: prefer Bash + scp/rsync with run_in_background=true.
This tool is primarily for Windows users without scp in PATH.
"""
import errno as _errno
import os
import stat as _stat

from ..connection import SSHConnection


def download(conn: SSHConnection, remote_path: str, local_path: str) -> str:
    """
    Pull a remote file to the LOCAL machine via SFTP.

    Args:
        conn: established SSHConnection.
        remote_path: absolute path on the remote host.
        local_path: absolute path on the local machine. `~` is expanded.
            Parent directory must exist (we don't auto-create local dirs).
            Overwrites if exists.

    Returns:
        `"Successfully downloaded <N> bytes from <remote_path> to <local_path>"` on success.
        `"Error: Remote file not found: <remote_path>"` if remote doesn't exist.
        `"Error: Remote path is a directory, not a file: <remote_path>"` if remote is a dir.
        `"Error: File too large for Download: <N> bytes exceeds transfer_size_cap
            (<cap> bytes). ..."` if remote file size > conn.config.transfer_size_cap.
            Error includes a ready-to-paste `Bash("scp ...", run_in_background=true)`
            template.
        `"Error: Local parent directory not found: <dir>"` if dirname(local_path)
            doesn't exist.
        `"Error: Permission denied: <local_path>"` if local write is denied.
        `"Error: <message>"` for other SFTP errors.
    """
    local = os.path.expanduser(local_path)
    local_parent = os.path.dirname(local) or "."
    if not os.path.isdir(local_parent):
        return f"Error: Local parent directory not found: {local_parent}"

    sftp = conn.get_sftp()
    # Stat remote to check existence, type, and size before transfer.
    try:
        st = sftp.stat(remote_path)
    except IOError:
        return f"Error: Remote file not found: {remote_path}"

    if _stat.S_ISDIR(st.st_mode or 0):
        return f"Error: Remote path is a directory, not a file: {remote_path}"

    size = st.st_size
    cap = conn.config.transfer_size_cap
    if size > cap:
        scp_template = (
            f"Bash(command=\"scp {conn.config.user}@{conn.config.hostname}:"
            f"{remote_path} {local_path}\", run_in_background=true)"
        )
        return (
            f"Error: File too large for Download: {size} bytes exceeds "
            f"transfer_size_cap ({cap} bytes). For files this size, the "
            f"right tool is Bash with scp or rsync: {scp_template}. It runs "
            f"in background, handles any size, and supports resume."
        )

    try:
        sftp.get(remote_path, local)
    except PermissionError:
        return f"Error: Permission denied: {local_path}"
    except (IOError, OSError) as e:
        if getattr(e, "errno", None) == _errno.EACCES:
            return f"Error: Permission denied: {local_path}"
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"

    return f"Successfully downloaded {size} bytes from {remote_path} to {local_path}"
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/integration/test_transfer_tools.py -v -k download`
Expected: All 4 download tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/download.py tests/integration/test_transfer_tools.py
git commit -m "feat(tools): Download — SFTP get with size cap + scp guidance"
```

---

## Task 4: RemoteInfo tool

**Files:**
- Create: `remote_mcp/tools/remote_info.py`
- Create: `tests/unit/test_remote_info.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_remote_info.py`:

```python
"""Unit tests for RemoteInfo — pure config formatting, no SSH."""
from remote_mcp.config import HostConfig
from remote_mcp.tools.remote_info import remote_info


class _FakeConn:
    def __init__(self, config):
        self.config = config


def test_remote_info_minimal_config():
    cfg = HostConfig(name="prod", hostname="10.0.0.1", user="ubuntu")
    out = remote_info(_FakeConn(cfg))
    assert "host=prod" in out
    assert "user=ubuntu" in out
    assert "hostname=10.0.0.1" in out
    assert "port=22" in out
    assert "jump_host=none" in out


def test_remote_info_full_config_with_jump():
    cfg = HostConfig(
        name="internal",
        hostname="10.0.0.50",
        user="admin",
        port=2222,
        jump_host="bastion",
    )
    out = remote_info(_FakeConn(cfg))
    assert "host=internal" in out
    assert "user=admin" in out
    assert "hostname=10.0.0.50" in out
    assert "port=2222" in out
    assert "jump_host=bastion" in out


def test_remote_info_output_is_5_lines():
    """Output is exactly the 5 documented fields, one per line."""
    cfg = HostConfig(name="x", hostname="h", user="u")
    out = remote_info(_FakeConn(cfg))
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 5
    field_names = {l.split("=", 1)[0] for l in lines}
    assert field_names == {"host", "user", "hostname", "port", "jump_host"}


def test_remote_info_no_ssh_calls_made():
    """
    RemoteInfo must NOT touch the connection. This is the VPN-safety
    guarantee: even if SSH is dead, the result is the configured
    identity (the one we connect TO), not what the remote reports.
    """
    cfg = HostConfig(name="prod", hostname="vpn-internal", user="alice")
    # Fake conn that raises if anyone tries to use it
    class _NoSSHConn:
        def __init__(self, config): self.config = config
        def __getattr__(self, name):
            raise AssertionError(f"RemoteInfo touched the connection: .{name}")

    out = remote_info(_NoSSHConn(cfg))
    assert "host=prod" in out
```

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_remote_info.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `remote_mcp/tools/remote_info.py`**

```python
"""RemoteInfo tool — report the connection's configured identity.

CRITICAL: This tool does NOT call SSH. It reads from conn.config and
returns the values we use to *connect* — not whatever the remote thinks
it is. In VPN scenarios, `hostname -I` on the remote returns
internal-network IPs that are not what the client uses to reach it.
For the agent to know "which host am I really operating on?" — the
authoritative answer is the config, not the remote's self-report.
"""


def remote_info(conn) -> str:
    """
    Return a structured summary of the connection's configured identity.

    Args:
        conn: established SSHConnection (only conn.config is accessed).

    Returns:
        5 lines, one per field, in key=value format:
            host=<config-key>
            user=<config-user>
            hostname=<config-hostname>
            port=<config-port>
            jump_host=<config-jump-host or "none">
    """
    c = conn.config
    return (
        f"host={c.name}\n"
        f"user={c.user}\n"
        f"hostname={c.hostname}\n"
        f"port={c.port}\n"
        f"jump_host={c.jump_host or 'none'}\n"
    )
```

- [ ] **Step 4: Run, PASS**

Run: `pytest tests/unit/test_remote_info.py -v`
Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote_mcp/tools/remote_info.py tests/unit/test_remote_info.py
git commit -m "feat(tools): RemoteInfo — report HostConfig identity (VPN-safe; no SSH call)"
```

---

## Task 5: Schemas + descriptions + server dispatch

**Files:**
- Modify: `remote_mcp/schemas.py`
- Modify: `remote_mcp/server.py`
- Modify: `tests/unit/test_schemas.py`
- Modify: `tests/integration/test_server.py`

- [ ] **Step 1: Update schemas test (expect 13 tools)**

Edit `tests/unit/test_schemas.py`, change the expected-tool set:

```python
def test_all_thirteen_tools_have_schemas():
    expected = {
        "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
        "Bash", "Glob", "Grep", "Feedback",
        "Upload", "Download", "RemoteInfo",
    }
    assert set(ALL_TOOL_SCHEMAS.keys()) == expected


def test_required_lists_for_new_tools():
    assert set(ALL_TOOL_SCHEMAS["Upload"]["required"]) == {"local_path", "remote_path"}
    assert set(ALL_TOOL_SCHEMAS["Download"]["required"]) == {"remote_path", "local_path"}
    assert ALL_TOOL_SCHEMAS["RemoteInfo"]["required"] == []  # no params
```

Rename the existing `test_all_ten_tools_have_schemas` to the new one (or replace its body); update the other tests that reference the count if needed.

- [ ] **Step 2: Run, FAIL**

Run: `pytest tests/unit/test_schemas.py -v`
Expected: FAIL — tools not registered.

- [ ] **Step 3: Implement — add 3 schemas + descriptions + register**

In `remote_mcp/schemas.py`, append (before the `ALL_TOOL_SCHEMAS` dict):

```python
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
```

Then update the `ALL_TOOL_SCHEMAS` dict — add three entries:

```python
    "Upload": UPLOAD_SCHEMA,
    "Download": DOWNLOAD_SCHEMA,
    "RemoteInfo": REMOTEINFO_SCHEMA,
```

Add descriptions (before `ALL_TOOL_DESCRIPTIONS` dict):

```python
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
```

Then update the `ALL_TOOL_DESCRIPTIONS` dict — add three entries.

In `remote_mcp/server.py`, add imports near the other tool imports:

```python
from .tools import upload as upload_tool
from .tools import download as download_tool
from .tools import remote_info as remote_info_tool
```

Add three dispatch arms in `_raw_dispatch`, before the final `return f"Error: unknown tool: {name}"`:

```python
    if name == "Upload":
        return upload_tool.upload(_conn, **args)
    if name == "Download":
        return download_tool.download(_conn, **args)
    if name == "RemoteInfo":
        return remote_info_tool.remote_info(_conn, **args)
```

- [ ] **Step 4: Update integration server test**

In `tests/integration/test_server.py`, find `test_list_tools_returns_ten` and rename/update:

```python
def test_list_tools_returns_thirteen(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        tools = asyncio.run(srv.list_tools())
        names = [t.name for t in tools]
        assert set(names) == {
            "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
            "Bash", "Glob", "Grep", "Feedback",
            "Upload", "Download", "RemoteInfo",
        }
    finally:
        srv._teardown_for_test()


def test_call_tool_dispatches_remote_info(runtime_config):
    srv._init_for_test(runtime_config, "test")
    try:
        result = asyncio.run(srv.call_tool("RemoteInfo", {}))
        text = result[0].text
        assert "host=test" in text
        assert "user=" in text
        assert "hostname=" in text
    finally:
        srv._teardown_for_test()
```

- [ ] **Step 5: Run, PASS**

Run: `pytest tests/unit/test_schemas.py tests/integration/test_server.py -v`
Expected: All schema and server tests pass.

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -v`
Expected: All passing (around 115+ tests now).

- [ ] **Step 7: Commit**

```bash
git add remote_mcp/schemas.py remote_mcp/server.py tests/unit/test_schemas.py tests/integration/test_server.py
git commit -m "feat(server): register Upload/Download/RemoteInfo (tool count 10 → 13)"
```

---

## Task 6: Reference docs (en + zh) for the 3 new tools

**Files:**
- Create: `docs/reference/tools/upload.md` + `.zh.md`
- Create: `docs/reference/tools/download.md` + `.zh.md`
- Create: `docs/reference/tools/remote-info.md` + `.zh.md`
- Modify: `docs/reference/README.md` + `.zh.md` (add 3 rows to Tool reference table)
- Modify: `docs/reference/config-schema.md` + `.zh.md` (document `transfer_size_cap`)
- Modify: `docs/reference/errors.md` + `.zh.md` (add 3 new tool sections)

- [ ] **Step 1: Create `docs/reference/tools/upload.md`**

```markdown
# Upload

> 中文版本：[upload.zh.md](./upload.zh.md)

Push a local file to the remote host via SFTP. Binary-safe.

**On Linux/macOS, prefer `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** — non-blocking, any size, resumable with `rsync`. Upload is primarily for Windows users without `scp` in PATH.

## Schema

```json
{
  "type": "object",
  "properties": {
    "local_path": {"type": "string"},
    "remote_path": {"type": "string"}
  },
  "required": ["local_path", "remote_path"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `local_path` | string | yes | — | Absolute path on the LOCAL machine. `~` is expanded. |
| `remote_path` | string | yes | — | Absolute path on the remote. Overwrites if exists. Parent directories are auto-created via SFTP `mkdir`. |

## Returns

A string.

**On success:** `Successfully uploaded <N> bytes from <local_path> to <remote_path>` where `<N>` is the byte length of the local file.

**On error:** one of the strings in [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| `local_path` does not exist | `Error: Local file not found: <local_path>` |
| `local_path` is a directory | `Error: Local path is a directory, not a file: <local_path>` |
| Local file size > `conn.config.transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Remote write denied (`PermissionError` or `IOError` with `errno=EACCES`) | `Error: Permission denied: <remote_path>` |
| Other SFTP failure | `Error: <message>` |

## Behavior notes

- Uses paramiko's `sftp.put(local, remote)` which streams the file — no full file load into memory. Suitable for files up to `transfer_size_cap`.
- Parent directory of `remote_path` is created recursively via SFTP `mkdir` (same mechanism as Write).
- The local file is read in binary mode; UTF-8 text encoding is NOT assumed.
- The transfer blocks until completion — there is no progress reporting. For large transfers, prefer `Bash + scp` in background.
- `transfer_size_cap` is checked via `os.path.getsize()` before transfer begins; nothing is transferred if the file is too large.

## Bandwidth/latency profile

- **Transfer size:** equal to the local file's byte length, subject to SSH compression.
- **Round-trips:** one SFTP session reused from the connection; one or more SFTP `mkdir` round-trips for parent path creation; one SFTP `put` (which itself involves multiple data packets but is one logical operation).
- **Blocks the conversation** for the duration of the transfer. For files where the transfer time matters, use `Bash("scp ...", run_in_background=true)`.

## See also

- [Download](./download.md) — the inverse
- [Write](./write.md) — text-only, in-memory content rather than from a local file path
- [Bash](./bash.md) — for the `scp` + `run_in_background=true` pattern
- [How-to: run long background jobs](../../how-to/run-long-background-jobs.md)
- Spec — *not in spec; added in v0.1.1*
```

- [ ] **Step 2: Create `docs/reference/tools/upload.zh.md`** (mirror translation)

```markdown
# Upload

> English version: [upload.md](./upload.md)

通过 SFTP 把本地文件推送到远程主机。二进制安全。

**Linux/macOS 用户优先用 `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** —— 非阻塞、不限大小、配合 `rsync` 可恢复。Upload 主要是为没有 `scp` 的 Windows 用户准备的兜底。

## Schema

```json
{
  "type": "object",
  "properties": {
    "local_path": {"type": "string"},
    "remote_path": {"type": "string"}
  },
  "required": ["local_path", "remote_path"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `local_path` | string | 是 | — | **本机**绝对路径。`~` 会展开。 |
| `remote_path` | string | 是 | — | 远程绝对路径。已存在则覆盖。父目录通过 SFTP `mkdir` 自动创建。 |

## 返回值

字符串。

**成功**：`Successfully uploaded <N> bytes from <local_path> to <remote_path>`，其中 `<N>` 是本地文件的字节数。

**失败**：见下面[错误措辞](#错误措辞)。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| `local_path` 不存在 | `Error: Local file not found: <local_path>` |
| `local_path` 是目录 | `Error: Local path is a directory, not a file: <local_path>` |
| 本地文件大小 > `conn.config.transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| 远程写入权限拒绝（`PermissionError` 或 `errno=EACCES` 的 `IOError`） | `Error: Permission denied: <remote_path>` |
| 其他 SFTP 失败 | `Error: <message>` |

## 行为说明

- 用 paramiko 的 `sftp.put(local, remote)`，流式传输——不会把整个文件读入内存。适合传输到 `transfer_size_cap` 上限以内的文件。
- `remote_path` 的父目录通过 SFTP `mkdir` 递归创建（与 Write 一致）。
- 本地文件按二进制方式读取，**不**假设 UTF-8。
- 传输期间阻塞——无进度上报。对大文件用 `Bash + scp` 后台模式更合适。
- `transfer_size_cap` 在传输开始前用 `os.path.getsize()` 检查；超限则不传任何字节。

## 带宽特征

- **传输大小**：等于本地文件字节数，受 SSH 压缩影响。
- **往返次数**：SFTP session 复用一份；父目录创建 1 个或多个 `mkdir` 往返；一次 SFTP `put`（内部多 packet 但是一次逻辑操作）。
- **阻塞对话**直到传输完成。对大文件用 `Bash("scp ...", run_in_background=true)`。

## 相关

- [Download](./download.zh.md) —— 反向
- [Write](./write.zh.md) —— 写文本字符串而不是本地文件路径
- [Bash](./bash.zh.md) —— 用于 `scp` + `run_in_background=true` 模式
- [操作指南：运行长时后台任务](../../how-to/run-long-background-jobs.zh.md)
- Spec —— *不在 spec 中；v0.1.1 新增*
```

- [ ] **Step 3: Create `docs/reference/tools/download.md`** (symmetric to upload.md)

Use the same structure. Key differences:
- Description: pull remote → local
- Parameters: `remote_path` first then `local_path`
- Error wording row for "Remote file not found" + "Local parent directory not found" + "Remote path is a directory"
- "See also" links to Upload

```markdown
# Download

> 中文版本：[download.zh.md](./download.zh.md)

Pull a remote file to the local machine via SFTP. Binary-safe.

**On Linux/macOS, prefer `Bash("scp <user>@<host>:<remote> <local>", run_in_background=true)`** — non-blocking, any size, resumable with `rsync`. Download is primarily for Windows users without `scp` in PATH.

## Schema

```json
{
  "type": "object",
  "properties": {
    "remote_path": {"type": "string"},
    "local_path": {"type": "string"}
  },
  "required": ["remote_path", "local_path"]
}
```

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `remote_path` | string | yes | — | Absolute path on the remote host. |
| `local_path` | string | yes | — | Absolute path on the LOCAL machine. `~` is expanded. Parent directory must already exist (not auto-created). Overwrites if exists. |

## Returns

A string.

**On success:** `Successfully downloaded <N> bytes from <remote_path> to <local_path>` where `<N>` is the remote file's byte length.

**On error:** see [Error wording](#error-wording).

## Error wording

| Trigger | Returned string |
|---------|-----------------|
| Local parent directory does not exist | `Error: Local parent directory not found: <dir>` |
| `remote_path` does not exist (SFTP `stat` raises `IOError`) | `Error: Remote file not found: <remote_path>` |
| `remote_path` is a directory | `Error: Remote path is a directory, not a file: <remote_path>` |
| Remote file size > `conn.config.transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Local write denied (`PermissionError` or `IOError` with `errno=EACCES`) | `Error: Permission denied: <local_path>` |
| Other SFTP failure | `Error: <message>` |

## Behavior notes

- Uses paramiko's `sftp.get(remote, local)` which streams the file.
- Remote `stat()` is called before the transfer to enforce the size cap and to give a clean "Remote file not found" error rather than a cryptic mid-transfer failure.
- The local parent directory must exist; Download does NOT auto-create local directories (asymmetric with Upload, which auto-creates remote dirs).
- Local file is written in binary mode.
- Blocks until completion; no progress reporting.

## Bandwidth/latency profile

- **Transfer size:** equal to the remote file's byte length, subject to SSH compression.
- **Round-trips:** 1 SFTP `stat` (cap check) + 1 SFTP `get`.
- **Blocks the conversation** for the transfer duration. For large files, use `Bash + scp` in background.

## See also

- [Upload](./upload.md) — the inverse
- [Read](./read.md) — server-side line slicing; doesn't write the file locally
- [Bash](./bash.md) — for `scp` + `run_in_background=true`
- [How-to: run long background jobs](../../how-to/run-long-background-jobs.md)
- Spec — *not in spec; added in v0.1.1*
```

- [ ] **Step 4: Create `docs/reference/tools/download.zh.md`** (mirror translation, structurally identical)

```markdown
# Download

> English version: [download.md](./download.md)

通过 SFTP 把远程文件拉到本机。二进制安全。

**Linux/macOS 用户优先用 `Bash("scp <user>@<host>:<remote> <local>", run_in_background=true)`** —— 非阻塞、不限大小、配合 `rsync` 可恢复。Download 主要是为没有 `scp` 的 Windows 用户准备的兜底。

## Schema

```json
{
  "type": "object",
  "properties": {
    "remote_path": {"type": "string"},
    "local_path": {"type": "string"}
  },
  "required": ["remote_path", "local_path"]
}
```

## 参数

| 名称 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `remote_path` | string | 是 | — | 远程绝对路径。 |
| `local_path` | string | 是 | — | **本机**绝对路径。`~` 会展开。父目录必须已存在（不自动创建）。已存在则覆盖。 |

## 返回值

字符串。

**成功**：`Successfully downloaded <N> bytes from <remote_path> to <local_path>`，其中 `<N>` 是远程文件字节数。

**失败**：见下面[错误措辞](#错误措辞)。

## 错误措辞

| 触发条件 | 返回字符串 |
|---------|-----------|
| 本地父目录不存在 | `Error: Local parent directory not found: <dir>` |
| `remote_path` 不存在（SFTP `stat` 抛 `IOError`） | `Error: Remote file not found: <remote_path>` |
| `remote_path` 是目录 | `Error: Remote path is a directory, not a file: <remote_path>` |
| 远程文件大小 > `conn.config.transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| 本地写入权限拒绝（`PermissionError` 或 `errno=EACCES` 的 `IOError`） | `Error: Permission denied: <local_path>` |
| 其他 SFTP 失败 | `Error: <message>` |

## 行为说明

- 用 paramiko 的 `sftp.get(remote, local)`，流式传输。
- 传输前先 SFTP `stat()`，既能严格 cap 检查，也能给出干净的"远程文件不存在"错误而非传输途中的隐晦失败。
- **本地父目录必须存在**；Download **不**自动创建本地目录（与 Upload 不对称——Upload 会自动建远程父目录）。
- 本地文件按二进制方式写入。
- 传输期间阻塞；无进度上报。

## 带宽特征

- **传输大小**：等于远程文件字节数，受 SSH 压缩影响。
- **往返次数**：1 次 SFTP `stat`（cap 检查）+ 1 次 SFTP `get`。
- **阻塞对话**直到传输完成。大文件用 `Bash + scp` 后台模式。

## 相关

- [Upload](./upload.zh.md) —— 反向
- [Read](./read.zh.md) —— 服务器端按行切片；不写本地文件
- [Bash](./bash.zh.md) —— `scp` + `run_in_background=true` 模式
- [操作指南：运行长时后台任务](../../how-to/run-long-background-jobs.zh.md)
- Spec —— *不在 spec 中；v0.1.1 新增*
```

- [ ] **Step 5: Create `docs/reference/tools/remote-info.md`**

```markdown
# RemoteInfo

> 中文版本：[remote-info.zh.md](./remote-info.zh.md)

Return the connection's **configured** identity — host label, user, hostname, port, jump_host. **No SSH call is made**; values come directly from `~/.config/remote-mcp/config.yaml`.

## Why this exists (not what — see Behavior notes)

In VPN scenarios, the IP the remote reports via `hostname -I` is an internal-network IP that does NOT match the IP the client uses to reach it. An agent asking "which host am I really operating on?" cannot trust `Bash("hostname -I")`. This tool returns the authoritative client-side answer.

## Schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## Parameters

None.

## Returns

A string of 5 lines, one per field, in `key=value` format:

```
host=<config-key>
user=<config-user>
hostname=<config-hostname>
port=<config-port>
jump_host=<config-jump-host or "none">
```

Example:

```
host=prod
user=ubuntu
hostname=10.0.0.50
port=22
jump_host=bastion
```

## Error wording

None — RemoteInfo cannot fail (it reads in-memory config that's already loaded; if config loading had failed, the MCP server wouldn't have started).

## Behavior notes

- Pure local lookup. Zero SSH traffic. Returns instantly.
- Values match what `connection.py` uses to build the paramiko `Transport`: the `hostname` is what we *connect to*, not what the remote *reports*.
- If you DO want the remote's self-reported identity (kernel, IPs as seen from inside), use `Bash("whoami && hostname && hostname -I && uname -a")` — but in VPN scenarios that answer may differ from `RemoteInfo`'s, and `RemoteInfo` is the connection-truth.
- The `jump_host` field is the name of another `hosts:` entry in `config.yaml`, or `none` if no jump is configured. RemoteInfo does NOT recursively expand the jump host's details — get them with a second call after switching connection.

## Bandwidth/latency profile

- **Transfer size:** zero bytes over SSH.
- **Round-trips:** zero.
- **Latency:** microseconds.

## See also

- [Configuration schema](../config-schema.md) — the source these fields are read from
- [Bash](./bash.md) — for asking the remote its self-reported identity
- [Explanation: multi-host model](../../explanation/multi-host-model.md) — why the `[host=X]` prefix is the config name, not the IP
- Spec — *not in spec; added in v0.1.1*
```

- [ ] **Step 6: Create `docs/reference/tools/remote-info.zh.md`** (mirror translation)

```markdown
# RemoteInfo

> English version: [remote-info.md](./remote-info.md)

返回**连接的已配置身份**——host 标签、用户名、主机名、端口、跳板主机。**不发任何 SSH 请求**；值直接来自 `~/.config/remote-mcp/config.yaml`。

## 为什么存在（不是"是什么"——见"行为说明"）

VPN 场景下，远程通过 `hostname -I` 报告的 IP 是内网 IP，**与客户端实际连接的 IP 不一致**。agent 想知道"我现在到底操作的是哪台主机？"时，不能信任 `Bash("hostname -I")` 的答案。本工具返回的就是客户端这一侧的权威答案。

## Schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## 参数

无。

## 返回值

5 行字符串，每行一个字段，`key=value` 格式：

```
host=<config-key>
user=<config-user>
hostname=<config-hostname>
port=<config-port>
jump_host=<config-jump-host or "none">
```

示例：

```
host=prod
user=ubuntu
hostname=10.0.0.50
port=22
jump_host=bastion
```

## 错误措辞

无——RemoteInfo 不会失败（它读取内存中已加载的配置；如果配置加载失败，MCP 服务器根本就不会启动）。

## 行为说明

- 纯本地查询。零 SSH 流量。瞬时返回。
- 值与 `connection.py` 构建 paramiko `Transport` 用的是同一份：`hostname` 是我们**实际连接**的目标，而**不是**远程报告的。
- 如果你**确实**想要远程自己报告的身份（内核、内部 IP 等），用 `Bash("whoami && hostname && hostname -I && uname -a")`——但在 VPN 场景下这个结果可能跟 `RemoteInfo` 不一致，且 `RemoteInfo` 才是连接侧的真相。
- `jump_host` 字段是 `config.yaml` 中 `hosts:` 块的另一个 entry 名称，或 `none`（如果未配置跳板）。RemoteInfo **不**递归展开跳板主机的详情——需要的话切换连接后再调一次。

## 带宽特征

- **传输大小**：0 字节（不经过 SSH）。
- **往返次数**：0。
- **延迟**：微秒级。

## 相关

- [配置 schema](../config-schema.zh.md) —— 这些字段的来源
- [Bash](./bash.zh.md) —— 用于问远程它自己报告的身份
- [概念说明：多主机模型](../../explanation/multi-host-model.zh.md) —— 为什么 `[host=X]` 前缀是 config 名称而不是 IP
- Spec —— *不在 spec 中；v0.1.1 新增*
```

- [ ] **Step 7: Update `docs/reference/README.md`** — add 3 rows to the tool table

Find the existing tool table (the one listing Read, Write, ..., Feedback) and add at the bottom (alphabetical / functional order — Upload/Download/RemoteInfo at the end is fine):

```markdown
| [Upload](./tools/upload.md) | Push a local file to the remote via SFTP (binary-safe). Windows convenience; Linux prefers Bash + scp. |
| [Download](./tools/download.md) | Pull a remote file to local via SFTP (binary-safe). Windows convenience; Linux prefers Bash + scp. |
| [RemoteInfo](./tools/remote-info.md) | Return the connection's configured identity (host, user, hostname, port, jump_host). No SSH call — VPN-safe. |
```

- [ ] **Step 8: Update `docs/reference/README.zh.md`** — same 3 rows in Chinese

```markdown
| [Upload](./tools/upload.zh.md) | 通过 SFTP 把本地文件推到远程（二进制安全）。Windows 兜底；Linux 优先 Bash + scp。 |
| [Download](./tools/download.zh.md) | 通过 SFTP 把远程文件拉到本地（二进制安全）。Windows 兜底；Linux 优先 Bash + scp。 |
| [RemoteInfo](./tools/remote-info.zh.md) | 返回连接的已配置身份（host、user、hostname、port、jump_host）。不发 SSH——VPN 安全。 |
```

- [ ] **Step 9: Update `docs/reference/config-schema.md`** — document `transfer_size_cap`

Find the per-host fields table and add this row (after `bash_output_cap`):

```markdown
| `transfer_size_cap` | int | No | 104857600 (100 MB) | Maximum file size in bytes that `Upload` or `Download` will transfer. Files larger than this return an `Error:` string that includes a ready-to-paste `Bash + scp` command. Raise this if you need larger transfers and don't want to switch to scp. |
```

Plus a sentence in the description prose that mentions it's the cap for Upload/Download.

- [ ] **Step 10: Update `docs/reference/config-schema.zh.md`** — same row in Chinese

```markdown
| `transfer_size_cap` | int | 否 | 104857600 (100 MB) | `Upload` 或 `Download` 单文件最大传输字节数。超过会返回 `Error:` 字符串，并附上可直接粘贴的 `Bash + scp` 命令。如确实需要传更大的文件而不想切到 scp，调高此值。 |
```

- [ ] **Step 11: Update `docs/reference/errors.md`** — add 3 new tool sections

Add after the existing Feedback section:

```markdown
### Upload

| Trigger | Returned string |
|---------|-----------------|
| `local_path` does not exist | `Error: Local file not found: <local_path>` |
| `local_path` is a directory | `Error: Local path is a directory, not a file: <local_path>` |
| Local file size > `transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Remote write denied | `Error: Permission denied: <remote_path>` |
| Other SFTP failure | `Error: <message>` |

### Download

| Trigger | Returned string |
|---------|-----------------|
| Local parent directory missing | `Error: Local parent directory not found: <dir>` |
| `remote_path` does not exist | `Error: Remote file not found: <remote_path>` |
| `remote_path` is a directory | `Error: Remote path is a directory, not a file: <remote_path>` |
| Remote file size > `transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| Local write denied | `Error: Permission denied: <local_path>` |
| Other SFTP failure | `Error: <message>` |

### RemoteInfo

RemoteInfo cannot fail — it returns the in-memory config. No error strings.
```

- [ ] **Step 12: Update `docs/reference/errors.zh.md`** — same in Chinese

```markdown
### Upload

| 触发条件 | 返回字符串 |
|---------|-----------|
| `local_path` 不存在 | `Error: Local file not found: <local_path>` |
| `local_path` 是目录 | `Error: Local path is a directory, not a file: <local_path>` |
| 本地文件大小 > `transfer_size_cap` | `Error: File too large for Upload: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <local> <user>@<host>:<remote>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| 远程写入权限拒绝 | `Error: Permission denied: <remote_path>` |
| 其他 SFTP 失败 | `Error: <message>` |

### Download

| 触发条件 | 返回字符串 |
|---------|-----------|
| 本地父目录缺失 | `Error: Local parent directory not found: <dir>` |
| `remote_path` 不存在 | `Error: Remote file not found: <remote_path>` |
| `remote_path` 是目录 | `Error: Remote path is a directory, not a file: <remote_path>` |
| 远程文件大小 > `transfer_size_cap` | `Error: File too large for Download: <N> bytes exceeds transfer_size_cap (<cap> bytes). For files this size, the right tool is Bash with scp or rsync: Bash(command="scp <user>@<host>:<remote> <local>", run_in_background=true). It runs in background, handles any size, and supports resume.` |
| 本地写入权限拒绝 | `Error: Permission denied: <local_path>` |
| 其他 SFTP 失败 | `Error: <message>` |

### RemoteInfo

RemoteInfo 不会失败——它返回内存中的配置。无错误字符串。
```

- [ ] **Step 13: Verify all link targets exist + commit**

Run:
```bash
python3 -c "
import re
from pathlib import Path
ROOT = Path('/home/lb/workspace/remote-mcp')
LINK = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
broken = 0; total = 0
for md in list(ROOT.glob('*.md')) + list((ROOT/'docs').rglob('*.md')):
    for _, t in LINK.findall(md.read_text()):
        if t.startswith(('http', '#', 'mailto:')): continue
        total += 1
        if not (md.parent / t.split('#')[0]).resolve().exists(): broken += 1
print(f'Total: {total}, broken: {broken}')
"
```
Expected: `broken: 0`.

Then commit:
```bash
git add docs/reference/
git commit -m "docs: reference pages for Upload/Download/RemoteInfo (en+zh) + config + errors catalog"
```

---

## Task 7: Update CLAUDE.md.fragment.md + CHANGELOG

**Files:**
- Modify: `CLAUDE.md.fragment.md` + `.zh.md`
- Modify: `CHANGELOG.md` + `.zh.md`

- [ ] **Step 1: Add transfer-rule to `CLAUDE.md.fragment.md`**

Find the "Shell 操作" section (or equivalent English `Shell operations`). In the English version, find the section header `### Single-host mode` → `**Shell operations**` bullet group, and add this bullet near the others about long-running operations:

```markdown
- For file transfers (binary or large): **prefer `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** over the `Upload` / `Download` tools. scp/rsync are non-blocking when launched in background and support any file size. The `Upload`/`Download` tools are a Windows fallback for users without scp in PATH, and they're capped at `transfer_size_cap` (default 100 MB). On Linux/macOS, scp wins on every axis.
```

- [ ] **Step 2: Mirror to `CLAUDE.md.fragment.zh.md`**

```markdown
- 文件传输（二进制或大文件）：**优先 `Bash("scp <local> <user>@<host>:<remote>", run_in_background=true)`** 而不是 `Upload` / `Download` 工具。scp/rsync 在后台模式下非阻塞、不限大小。`Upload`/`Download` 是给 PATH 中无 scp 的 Windows 用户的兜底，且受 `transfer_size_cap` 限制（默认 100 MB）。Linux/macOS 上 scp 在每个维度都更好。
```

- [ ] **Step 3: Add v0.1.1 section to `CHANGELOG.md`**

Edit the `[Unreleased]` section heading or insert above it:

```markdown
## [0.1.1] - Unreleased

### Added

Three new tools — total tool count now 13:

- **`Upload(local_path, remote_path)`** — push a local file to the remote via SFTP. Binary-safe. Preflight checks for existence, type (must be a file), and size (must be ≤ `transfer_size_cap`). Parent directories on the remote are auto-created. For Linux/macOS, the tool description and oversized-file error both steer the agent to `Bash("scp ...", run_in_background=true)` instead — non-blocking, no size limit, resumable. Upload is the Windows-without-scp fallback.

- **`Download(remote_path, local_path)`** — pull a remote file to local via SFTP. Symmetric to Upload (same cap, same scp guidance). Pre-checks remote existence and size via SFTP `stat`. Local parent directory must already exist (not auto-created — asymmetric with Upload).

- **`RemoteInfo()`** — return the connection's configured identity in 5 `key=value` lines (`host`, `user`, `hostname`, `port`, `jump_host`). **Issues no SSH call** — reads `conn.config`. VPN-safe: in VPN scenarios the remote's `hostname -I` returns internal-network IPs that don't match the IP the client uses; this tool returns the latter.

### Added (config)

- `HostConfig.transfer_size_cap` — int, default `100 * 1024 * 1024` (100 MB). Caps `Upload` / `Download` per-file size. Files larger return an `Error: ...` with a ready-to-paste `Bash + scp` command.

### Changed

- `CLAUDE.md.fragment.md`: new rule advising agents to prefer `Bash + scp` for transfers on Linux/macOS; Upload/Download positioned explicitly as Windows fallback.
```

- [ ] **Step 4: Mirror to `CHANGELOG.zh.md`**

```markdown
## [0.1.1] - 未发布

### 新增

三个新工具——工具总数现为 13：

- **`Upload(local_path, remote_path)`** —— 通过 SFTP 把本地文件推到远程。二进制安全。前置检查：存在性、类型（必须是文件）、大小（必须 ≤ `transfer_size_cap`）。远程父目录自动创建。Linux/macOS 上，工具描述与超大文件错误都引导 agent 改用 `Bash("scp ...", run_in_background=true)`——非阻塞、不限大小、可恢复。Upload 是 Windows-无-scp 的兜底。

- **`Download(remote_path, local_path)`** —— 通过 SFTP 把远程文件拉到本地。与 Upload 对称（同 cap、同 scp 引导）。传输前用 SFTP `stat` 检查远程存在性和大小。本地父目录必须已存在（不自动创建——与 Upload 不对称）。

- **`RemoteInfo()`** —— 返回连接的已配置身份，5 行 `key=value`（`host`、`user`、`hostname`、`port`、`jump_host`）。**不发 SSH 请求**——读 `conn.config`。VPN 安全：VPN 场景下远程 `hostname -I` 返回内网 IP，与客户端连接的 IP 不一致；本工具返回后者。

### 新增（配置）

- `HostConfig.transfer_size_cap` —— int，默认 `100 * 1024 * 1024`（100 MB）。`Upload` / `Download` 单文件大小上限。超出返回 `Error: ...`，并附上可直接粘贴的 `Bash + scp` 命令。

### 变更

- `CLAUDE.md.fragment.md`：新增规则，引导 agent 在 Linux/macOS 上优先用 `Bash + scp` 做传输；Upload/Download 明确定位为 Windows 兜底。
```

- [ ] **Step 5: Commit + final full test**

```bash
git add CLAUDE.md.fragment.md CLAUDE.md.fragment.zh.md CHANGELOG.md CHANGELOG.zh.md
git commit -m "docs: CHANGELOG v0.1.1 + CLAUDE.md.fragment scp-preference rule (en+zh)"

# Final verification
pytest tests/ -v
```
Expected: all tests pass; total count around 115+.

---

## Self-review (done in plan-writer's head)

- **Spec coverage**: 3 tools requested → 3 tool-implementation tasks (2-4) + 1 registration task (5) + 1 docs task (6) + 1 CHANGELOG task (7). `transfer_size_cap` is covered in Task 1. VPN-safety constraint for RemoteInfo enforced by `test_remote_info_no_ssh_calls_made` in Task 4. scp-guidance in errors is asserted in Task 2 step 1 (test_upload_exceeds_size_cap asserts `"scp" in out` and `"run_in_background=true" in out`) and Task 3 step 1 (test_download_exceeds_size_cap, same assertions).

- **Placeholder scan**: no TBD/TODO. All code blocks complete. Error strings literal everywhere.

- **Type consistency**: function names `upload`, `download`, `remote_info` consistent across implementation, tests, schemas registration, and server dispatch. Module names `upload`, `download`, `remote_info` consistent. The `conn.config.transfer_size_cap` field accessed identically across upload/download.

Plan complete.
