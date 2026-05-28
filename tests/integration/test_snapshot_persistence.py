"""bug #4 — snapshot lives in ~/.cache and is cached locally. v0.2.2."""
import os

import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection


@pytest.fixture
def conn(sshd_container, ssh_key):
    cfg = HostConfig(
        name="snaptest",
        hostname=sshd_container["host"],
        port=sshd_container["port"],
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
    )
    c = SSHConnection(cfg)
    c.connect()
    yield c
    c.close()


def test_snapshot_path_under_home_cache(conn):
    """Snapshot file lives at ~/.cache/remote-mcp/snapshot-<pid>.sh."""
    assert conn._snapshot_path is not None
    pid = os.getpid()
    expected_suffix = f"/.cache/remote-mcp/snapshot-{pid}.sh"
    assert conn._snapshot_path.endswith(expected_suffix), (
        f"snapshot path {conn._snapshot_path!r} does not end with "
        f"{expected_suffix!r}"
    )


def test_snapshot_content_cached_locally(conn):
    """Content captured at connect is held in self._snapshot_content."""
    assert conn._snapshot_content is not None
    assert isinstance(conn._snapshot_content, bytes)
    assert b"declare" in conn._snapshot_content  # has env data


def test_snapshot_remote_home_resolved_and_cached(conn):
    """_remote_home is populated after connect and starts with /."""
    assert conn._remote_home is not None
    assert conn._remote_home.startswith("/")


def test_snapshot_file_exists_on_remote(conn):
    """The uploaded file is actually on the remote."""
    r = conn.exec(f"test -f {conn._snapshot_path} && echo OK")
    assert r.stdout.strip() == "OK"
