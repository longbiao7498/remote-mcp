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


def test_host_config_cwd_default_is_none():
    cfg = HostConfig(name="x", hostname="h", user="u")
    assert cfg.cwd is None


def test_load_config_with_cwd(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        hosts:
          prod:
            hostname: 10.0.0.1
            user: ubuntu
            cwd: /opt/myapp
          home:
            hostname: 10.0.0.2
            user: alice
            cwd: ~/projects/myapp
    """).strip())
    root = load_config(str(cfg))
    assert root.hosts["prod"].cwd == "/opt/myapp"
    assert root.hosts["home"].cwd == "~/projects/myapp"


def test_host_config_op_timeout_default_is_60():
    cfg = HostConfig(name="x", hostname="h", user="u")
    assert cfg.op_timeout_default == 60


def test_load_config_with_op_timeout_default(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        hosts:
          prod:
            hostname: 10.0.0.1
            user: ubuntu
            op_timeout_default: 30
    """).strip())
    root = load_config(str(cfg))
    assert root.hosts["prod"].op_timeout_default == 30
