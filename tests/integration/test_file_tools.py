import pytest

from remote_mcp.config import HostConfig
from remote_mcp.connection import SSHConnection
from remote_mcp.tools import read as read_tool
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


def test_write_permission_denied_returns_error(conn):
    """Write to a path the test user can't write to → returns Error string, doesn't raise."""
    # /etc is root-only on the test host
    out = write_tool.write(conn, "/etc/rmcp-cannot-write.txt", "x")
    assert out.startswith("Error:")
    assert "/etc/rmcp-cannot-write.txt" in out


def test_write_invalid_path_returns_error(conn):
    """Writing to an obviously invalid path → returns Error, doesn't raise."""
    # / is a directory, not a writable file
    out = write_tool.write(conn, "/", "x")
    assert out.startswith("Error:")


def test_write_special_chars(conn):
    raw = "it's a $VAR with \"quotes\" and \\backslash\nplus newline"
    write_tool.write(conn, "/tmp/rmcp-w-special.txt", raw)
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-w-special.txt", "r") as f:
        assert f.read().decode() == raw


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
    # Line numbers should be included (agent feedback enhancement)
    assert "lines 1, 2, 3" in out
    assert "replace_all=true" in out
    # File unchanged
    sftp = conn.get_sftp()
    with sftp.file("/tmp/rmcp-edit-3.txt", "r") as f:
        assert f.read().decode() == "foo\nfoo\nfoo\n"


def test_edit_file_not_found(conn):
    out = edit_tool.edit(conn, "/tmp/rmcp-edit-nope-xyz", "a", "b")
    assert out.startswith("Error: File not found:")


from remote_mcp.tools import multi_read as mr_tool
from remote_mcp.tools import multi_edit as me_tool


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
