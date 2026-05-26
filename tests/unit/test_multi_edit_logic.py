from remote_mcp.tools.multi_edit import apply_edits


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


def test_apply_edits_replace_all():
    content = "foo foo foo"
    edits = [{"old_string": "foo", "new_string": "X", "replace_all": True}]
    out, err = apply_edits(content, edits)
    assert err is None
    assert out == "X X X"
