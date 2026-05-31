"""Unit tests for Bash background param validation (spec §5.3.1)."""
import re

import pytest

from remote_mcp.tools.bash import _validate_name, _generate_name, _truncate_description


def test_valid_names():
    for n in ("foo", "x86_python_build", "bg-abc", "v1.2.3", "A_B-c.D"):
        assert _validate_name(n) is None  # None = no error


def test_invalid_names():
    for n in ("", "x" * 65, "foo bar", "foo/bar", "你好", "foo+bar"):
        err = _validate_name(n)
        assert err is not None
        assert "Error: invalid job name" in err


def test_generate_name_format():
    n = _generate_name()
    assert re.fullmatch(r"bg-[0-9a-f]{12}", n)


def test_generate_name_unique():
    seen = {_generate_name() for _ in range(100)}
    assert len(seen) == 100  # uuids don't collide in 100 tries


def test_truncate_description_under_limit():
    desc, truncated = _truncate_description("short")
    assert desc == "short"
    assert truncated is False


def test_truncate_description_over_limit():
    long = "x" * 600
    desc, truncated = _truncate_description(long)
    assert len(desc) == 500
    assert truncated is True
