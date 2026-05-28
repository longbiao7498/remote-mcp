import pytest

from remote_mcp.paths import resolve_path


def test_absolute_path_returns_as_is():
    assert resolve_path("/etc/passwd", "/opt/app") == "/etc/passwd"
    assert resolve_path("/", "/opt/app") == "/"


def test_relative_path_joined_to_cwd():
    assert resolve_path("foo.txt", "/opt/app") == "/opt/app/foo.txt"
    assert resolve_path("sub/foo.txt", "/opt/app") == "/opt/app/sub/foo.txt"


def test_dot_relative_path():
    assert resolve_path("./foo.txt", "/opt/app") == "/opt/app/foo.txt"
    assert resolve_path(".", "/opt/app") == "/opt/app"


def test_dotdot_relative_path_allowed_to_escape():
    # No sandbox — agent can step out of cwd. Aligns with CC native.
    assert resolve_path("../sibling.txt", "/opt/app") == "/opt/sibling.txt"


def test_empty_path_raises():
    with pytest.raises(ValueError, match="empty path"):
        resolve_path("", "/opt/app")


def test_tilde_path_raises():
    with pytest.raises(ValueError, match="starts with '~'"):
        resolve_path("~/foo", "/opt/app")
    with pytest.raises(ValueError, match="starts with '~'"):
        resolve_path("~", "/opt/app")


def test_trailing_slash_preserved_for_normpath():
    # normpath strips trailing slash — fine; OS-level tools don't care.
    assert resolve_path("dir/", "/opt/app") == "/opt/app/dir"
