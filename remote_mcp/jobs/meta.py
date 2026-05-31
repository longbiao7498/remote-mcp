"""meta.json read/write + atomic id allocation + state cache + lifecycle moves."""
import fcntl
import json
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from .paths import (
    local_sid_host_dir, local_archive_dir, local_zombie_dir,
    local_meta_path, local_status_path,
    local_next_id_path, local_id_lock_path,
)


_META_FNAME_RE = re.compile(r"^(\d+)-meta\.json$")


def read_meta(path: Path) -> dict:
    return json.loads(path.read_text())


def write_meta(sid: str, host: str, meta: dict) -> None:
    """Write meta.json to active dir (atomic via temp + rename)."""
    target = local_meta_path(sid, host, meta["id"])
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(tmp, target)


def allocate_id(sid: str, host: str) -> int:
    """Read next_id, increment by 1, write back. Atomic via fcntl flock."""
    lock_path = local_id_lock_path(sid, host)
    next_id_path = local_next_id_path(sid, host)
    with open(lock_path, "w") as lock_fp:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
        try:
            current = int(next_id_path.read_text().strip() or "0")
        except FileNotFoundError:
            current = 0
        new_id = current + 1
        tmp = next_id_path.with_suffix(".tmp")
        tmp.write_text(str(new_id))
        os.replace(tmp, next_id_path)
        return new_id


def write_state(sid: str, host: str, id_: int, state: str,
                state_at_unix: int, in_dir: str) -> None:
    """Update state + state_at_unix in the meta at the given location.

    in_dir: 'active', 'archive', or 'zombie'.
    """
    path = _path_for_location(sid, host, id_, in_dir)
    meta = read_meta(path)
    meta["state"] = state
    meta["state_at_unix"] = state_at_unix
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(tmp, path)


def _path_for_location(sid: str, host: str, id_: int, location: str) -> Path:
    if location == "active":
        return local_meta_path(sid, host, id_)
    if location == "archive":
        return local_archive_dir(sid, host) / f"{id_}-meta.json"
    if location == "zombie":
        return local_zombie_dir(sid, host) / f"{id_}-meta.json"
    raise ValueError(f"unknown location: {location}")


def _list_dir_metas(dir_: Path) -> list:
    out = []
    if not dir_.is_dir():
        return out
    for child in dir_.iterdir():
        m = _META_FNAME_RE.match(child.name)
        if not m:
            continue
        try:
            out.append(read_meta(child))
        except Exception:
            continue  # corrupt meta: caller surfaces via errors[]
    return out


def list_active_metas(sid: str, host: str) -> list:
    return _list_dir_metas(local_sid_host_dir(sid, host))


def list_archive_metas(sid: str, host: str) -> list:
    return _list_dir_metas(local_archive_dir(sid, host))


def list_zombie_metas(sid: str, host: str) -> list:
    return _list_dir_metas(local_zombie_dir(sid, host))


def find_meta_by_id_anywhere(sid: str, host: str,
                             id_: int) -> tuple:
    """Search active → archive → zombie. Returns (meta, location) or (None, None)."""
    for loc in ("active", "archive", "zombie"):
        path = _path_for_location(sid, host, id_, loc)
        if path.exists():
            return read_meta(path), loc
    return None, None


def find_meta_by_name_anywhere(sid: str, host: str,
                               name: str) -> tuple:
    """Search active → archive → zombie by name. Returns (meta, location) or (None, None)."""
    for loc, listing in (
        ("active", list_active_metas(sid, host)),
        ("archive", list_archive_metas(sid, host)),
        ("zombie", list_zombie_metas(sid, host)),
    ):
        for m in listing:
            if m["name"] == name:
                return m, loc
    return None, None


def move_to_archive(sid: str, host: str, id_: int) -> None:
    _move(sid, host, id_, local_archive_dir(sid, host))


def move_to_zombie(sid: str, host: str, id_: int) -> None:
    _move(sid, host, id_, local_zombie_dir(sid, host))


def _move(sid: str, host: str, id_: int, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    meta_src = local_meta_path(sid, host, id_)
    if meta_src.exists():
        shutil.move(str(meta_src), str(dest_dir / meta_src.name))
    status_src = local_status_path(sid, host, id_)
    if status_src.exists():
        shutil.move(str(status_src), str(dest_dir / status_src.name))
