from remote_mcp.tools.edit import _match_line_numbers
from remote_mcp.tools.multi_edit import apply_edits


# ---- _match_line_numbers (shared helper for Edit and MultiEdit errors) ----

def test_match_line_numbers_basic():
    content = "alpha\nfoo\nbeta\nfoo\ngamma\nfoo\n"
    assert _match_line_numbers(content, "foo") == "2, 4, 6"


def test_match_line_numbers_single_match():
    assert _match_line_numbers("alpha\nfoo\nbeta\n", "foo") == "2"


def test_match_line_numbers_no_match():
    assert _match_line_numbers("alpha\nbeta\n", "missing") == ""


def test_match_line_numbers_caps_at_10():
    # 12 matches → first 10 listed, then "... +2 more"
    content = "".join("foo\n" for _ in range(12))
    result = _match_line_numbers(content, "foo")
    assert result.startswith("1, 2, 3, 4, 5, 6, 7, 8, 9, 10, ... +2 more")


def test_match_line_numbers_multiline_old_string():
    content = "alpha\nstart\nmiddle\nend\nbeta\nstart\nmiddle\nend\n"
    # The "start\nmiddle\nend" pattern occurs starting at lines 2 and 6.
    assert _match_line_numbers(content, "start\nmiddle\nend") == "2, 6"


def test_match_line_numbers_non_overlapping():
    # "aaa" in "aaaaa" — non-overlapping matches at positions 0 and 3
    # offsets → line 1, line 1
    content = "aaaaa"
    assert _match_line_numbers(content, "aaa") == "1"  # Only 1 non-overlapping match


# ---- apply_edits ----

def test_apply_edits_sequential():
    content = "alpha\nbeta\ngamma\n"
    edits = [
        {"old_string": "alpha", "new_string": "A"},
        {"old_string": "gamma", "new_string": "G"},
    ]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "A\nbeta\nG\n"


def test_apply_edits_uses_prior_result():
    """Each subsequent edit operates on the result of the prior."""
    content = "foo"
    edits = [
        {"old_string": "foo", "new_string": "bar"},
        {"old_string": "bar", "new_string": "baz"},
    ]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "baz"


def test_apply_edits_zero_match_fails_atomically():
    content = "foo bar"
    edits = [
        {"old_string": "foo", "new_string": "FOO"},
        {"old_string": "nothing", "new_string": "X"},  # fails
    ]
    out, err = apply_edits(content, edits)
    assert err is not None
    assert "edit #2" in err
    assert "old_string not found" in err
    assert out is None  # atomic: no partial result


def test_apply_edits_multi_match_without_replace_all_fails():
    content = "foo foo"
    edits = [{"old_string": "foo", "new_string": "X"}]
    out, err = apply_edits(content, edits)
    assert err is not None
    assert "edit #1" in err
    assert "found 2 times" in err
    # Line numbers should be included
    assert "lines 1, 1" in err  # both occurrences on line 1


def test_apply_edits_replace_all():
    content = "foo foo foo"
    edits = [{"old_string": "foo", "new_string": "X", "replace_all": True}]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "X X X"
