import json
from pathlib import Path

from remote_mcp.tools.feedback import feedback


class _FakeConfig:
    def __init__(self, name, feedback_path):
        self.name = name
        self.feedback_path = feedback_path


class _FakeConn:
    def __init__(self, name, feedback_path):
        self.config = _FakeConfig(name, feedback_path)


def test_feedback_writes_jsonl_entry(tmp_path: Path):
    fpath = tmp_path / "fb.jsonl"
    conn = _FakeConn("prod", str(fpath))
    out = feedback(conn, str(fpath), "bug", "Glob ** broke", "details here")
    assert out.startswith("Feedback recorded: [bug] Glob ** broke")

    lines = fpath.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["category"] == "bug"
    assert entry["summary"] == "Glob ** broke"
    assert entry["details"] == "details here"
    assert entry["host"] == "prod"
    assert "ts" in entry
    assert "session_pid" in entry


def test_feedback_creates_parent_dir(tmp_path: Path):
    fpath = tmp_path / "sub" / "dirs" / "fb.jsonl"
    conn = _FakeConn("h", str(fpath))
    feedback(conn, str(fpath), "enhancement", "Add X")
    assert fpath.exists()


def test_feedback_rejects_invalid_category(tmp_path: Path):
    fpath = tmp_path / "fb.jsonl"
    conn = _FakeConn("h", str(fpath))
    out = feedback(conn, str(fpath), "wishlist", "x")
    assert out.startswith("Error: category must be")
    # File must not be created
    assert not fpath.exists()


def test_feedback_rejects_empty_summary(tmp_path: Path):
    fpath = tmp_path / "fb.jsonl"
    conn = _FakeConn("h", str(fpath))
    out = feedback(conn, str(fpath), "bug", "")
    assert out == "Error: summary cannot be empty"
    assert not fpath.exists()


def test_feedback_concurrent_appends_atomic(tmp_path: Path):
    """Simulate concurrent writes; lines should be intact (no interleaving)."""
    import multiprocessing as mp
    fpath = tmp_path / "fb.jsonl"

    def worker(i):
        conn = _FakeConn(f"h{i}", str(fpath))
        for j in range(20):
            feedback(conn, str(fpath), "bug", f"sum-{i}-{j}", "x" * 100)

    procs = [mp.Process(target=worker, args=(i,)) for i in range(4)]
    for p in procs: p.start()
    for p in procs: p.join()

    lines = fpath.read_text().splitlines()
    assert len(lines) == 80
    for ln in lines:
        json.loads(ln)  # each is valid JSON
