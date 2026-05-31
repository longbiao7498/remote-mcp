"""Unit tests for sid derivation (spec §12.1)."""
import re
from unittest.mock import patch

import pytest

from remote_mcp.jobs import sid as sid_module
from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test


@pytest.fixture(autouse=True)
def _reset():
    reset_cache_for_test()
    yield
    reset_cache_for_test()


def test_derive_sid_happy_returns_12hex_and_source():
    s, source = derive_sid()
    assert re.fullmatch(r"[0-9a-f]{12}", s)
    assert source == "ppid+starttime"


def test_derive_sid_is_cached():
    s1, _ = derive_sid()
    s2, _ = derive_sid()
    assert s1 == s2


def test_derive_sid_falls_back_when_psutil_raises():
    with patch.object(sid_module, "psutil") as mock_psutil:
        mock_psutil.Process.side_effect = RuntimeError("simulated")
        s, source = derive_sid()
        assert re.fullmatch(r"[0-9a-f]{12}", s)
        assert source.startswith("uuid (psutil fallback:")
        assert "simulated" in source


def test_derive_sid_falls_back_when_psutil_missing():
    with patch.object(sid_module, "psutil", None):
        s, source = derive_sid()
        assert re.fullmatch(r"[0-9a-f]{12}", s)
        assert "psutil not installed" in source
