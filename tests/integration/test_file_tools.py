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
