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
