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
