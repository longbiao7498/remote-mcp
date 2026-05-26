from remote_mcp.bash_session import parse_sentinel_line


def test_parse_sentinel_basic():
    line = "RMCP_SENTINEL_abc123_EXIT_0_CWD_/home/user\n"
    uuid = "abc123"
    parsed = parse_sentinel_line(line, uuid)
    assert parsed == (0, "/home/user")


def test_parse_sentinel_non_zero_exit():
    line = "RMCP_SENTINEL_xyz_EXIT_127_CWD_/tmp\n"
    assert parse_sentinel_line(line, "xyz") == (127, "/tmp")


def test_parse_sentinel_cwd_with_spaces():
    line = "RMCP_SENTINEL_u_EXIT_0_CWD_/home/user with space/dir\n"
    assert parse_sentinel_line(line, "u") == (0, "/home/user with space/dir")


def test_parse_sentinel_wrong_uuid_returns_none():
    line = "RMCP_SENTINEL_other_EXIT_0_CWD_/tmp\n"
    assert parse_sentinel_line(line, "mine") is None


def test_parse_sentinel_non_sentinel_returns_none():
    assert parse_sentinel_line("regular output line\n", "anything") is None
    assert parse_sentinel_line("", "anything") is None
