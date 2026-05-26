import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import glob as glob_mod
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
    out = glob_mod.glob_tool(conn, "*.py", "/tmp/rmcp-glob-test")
    assert "a.py" in out
    assert "c.py" in out
    assert "d.py" in out
    assert "b.txt" not in out


def test_glob_path_segment(conn):
    out = glob_mod.glob_tool(conn, "src/**/*.py", "/tmp/rmcp-glob-test")
    assert "src/c.py" in out or "src/sub/d.py" in out
    # Should NOT match top-level a.py
    assert "/a.py" not in out.replace("/src/", "/SRC/")  # simple disambig


def test_glob_no_matches(conn):
    out = glob_mod.glob_tool(conn, "*.nonexistent", "/tmp/rmcp-glob-test")
    assert out == "No files found matching pattern"
