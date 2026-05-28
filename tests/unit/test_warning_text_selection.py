"""bug #4 — WARNING text reflects snapshot state. v0.2.2."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from remote_mcp import server as srv


def _make_fake_conn(snapshot_error=None, snapshot_reuploaded=False,
                    reconnected=True, startup_warning_pending=False,
                    cwd="/opt/myapp", name="prod"):
    c = MagicMock()
    c.config.name = name
    c.config.cwd = cwd
    c._snapshot_error = snapshot_error
    c._snapshot_reuploaded = snapshot_reuploaded
    c._startup_warning_pending = startup_warning_pending
    # check_and_clear_reconnect_flag returns reconnected, then sets False
    c.check_and_clear_reconnect_flag.return_value = reconnected
    return c


def test_warning_case_a_reuse_only(monkeypatch):
    """Case A: reconnect, file present, no re-upload. Generic WARNING."""
    conn = _make_fake_conn(snapshot_reuploaded=False, snapshot_error=None)
    monkeypatch.setattr(srv, "_conn", conn)
    monkeypatch.setattr(srv, "_with_retry", lambda call: "ok")

    result = asyncio.run(srv.call_tool("Glob", {"pattern": "*"}))
    text = result[0].text

    assert "[WARNING] SSH connection to prod was lost and has been re-established." in text
    assert "snapshot file was missing" not in text.lower()
    assert "subsequent bash" not in text.lower()


def test_warning_case_b_reuploaded(monkeypatch):
    """Case B: reconnect + re-upload succeeded → explain re-upload."""
    conn = _make_fake_conn(snapshot_reuploaded=True, snapshot_error=None)
    monkeypatch.setattr(srv, "_conn", conn)
    monkeypatch.setattr(srv, "_with_retry", lambda call: "ok")

    result = asyncio.run(srv.call_tool("Glob", {"pattern": "*"}))
    text = result[0].text

    assert "re-uploaded from the local cache" in text
    assert "environment captured at session start has been preserved" in text


def test_warning_case_c_reupload_failed(monkeypatch):
    """Case C: reconnect + re-upload failed → warn of degraded environment."""
    conn = _make_fake_conn(
        snapshot_reuploaded=True,
        snapshot_error="snapshot upload failed: [Errno 28] No space",
    )
    monkeypatch.setattr(srv, "_conn", conn)
    monkeypatch.setattr(srv, "_with_retry", lambda call: "ok")

    result = asyncio.run(srv.call_tool("Glob", {"pattern": "*"}))
    text = result[0].text

    assert "re-upload failed" in text.lower()
    assert "[Errno 28]" in text
    assert "without the user's PATH/aliases" in text
    assert "/opt/myapp" in text  # configured cwd should appear


def test_warning_startup_failure_shown_once(monkeypatch):
    """Startup snapshot failure → one WARNING on first call, then cleared."""
    conn = _make_fake_conn(
        snapshot_error="snapshot capture failed: bashrc broken",
        startup_warning_pending=True,
        reconnected=False,
    )
    monkeypatch.setattr(srv, "_conn", conn)
    monkeypatch.setattr(srv, "_with_retry", lambda call: "ok")

    result = asyncio.run(srv.call_tool("Glob", {"pattern": "*"}))
    text = result[0].text

    assert "Session-start snapshot capture failed" in text
    assert "bashrc broken" in text
    # After consumption, flag must be cleared
    assert conn._startup_warning_pending is False
