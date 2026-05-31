"""bug #1 — Edit/MultiEdit/Bash must NOT be auto-retried. v0.2.2."""
from unittest.mock import patch, MagicMock

import paramiko
import pytest

from remote_mcp import server as srv


def test_no_retry_tools_constant():
    # v0.3.0 extended NO_RETRY_TOOLS with panel mutation tools (spec §2 table)
    assert srv.NO_RETRY_TOOLS == frozenset({
        "Edit", "MultiEdit", "Bash",
        "JobKill", "JobArchive", "JobScript",
    })


def test_with_reconnect_only_returns_error_string_on_ssh_failure():
    """_with_reconnect_only catches SSH errors and returns Error: ... string
    without re-executing the call."""
    fake_conn = MagicMock()
    call_count = {"n": 0}

    def call():
        call_count["n"] += 1
        raise paramiko.SSHException("boom")

    with patch.object(srv, "_conn", fake_conn):
        result = srv._with_reconnect_only(call)

    assert call_count["n"] == 1, (
        f"_with_reconnect_only must NOT retry; got {call_count['n']} calls"
    )
    assert result.startswith("Error:")
    assert "SSHException" in result or "boom" in result
    fake_conn._do_reconnect.assert_called_once()


def test_with_reconnect_only_returns_error_even_if_reconnect_fails():
    """If reconnect fails, the original error is still returned."""
    fake_conn = MagicMock()
    fake_conn._do_reconnect.side_effect = Exception("reconnect failed")

    def call():
        raise paramiko.SSHException("original boom")

    with patch.object(srv, "_conn", fake_conn):
        result = srv._with_reconnect_only(call)

    assert result.startswith("Error:")
    assert "original boom" in result or "SSHException" in result
