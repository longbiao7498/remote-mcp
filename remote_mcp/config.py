"""Configuration loading. See spec §11."""
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
    transfer_size_cap: int = 100 * 1024 * 1024   # 100 MB cap for Upload/Download


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
