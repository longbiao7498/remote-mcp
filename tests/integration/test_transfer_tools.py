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
    # /etc requires root on the test host
    out = upload_tool.upload(conn, str(local), "/etc/rmcp-cannot-write.txt")
    assert out.startswith("Error: Permission denied:")
    assert "/etc/rmcp-cannot-write.txt" in out
