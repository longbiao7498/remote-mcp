from remote_mcp.tools.glob import _glob_to_find_expr


def test_simple_filename():
    # "*.py" → -name '*.py'
    assert _glob_to_find_expr("*.py") == "-name '*.py'"


def test_recursive_double_star_filename():
    # "**/*.py" → equivalent to -name '*.py' (find recurses by default)
    assert _glob_to_find_expr("**/*.py") == "-name '*.py'"


def test_path_segment_pattern():
    # "src/*.c" → -wholename '*/src/*.c'
    # (* matches a single segment; the leading */ allows match at any depth)
    assert _glob_to_find_expr("src/*.c") == "-wholename '*/src/*.c'"


def test_path_with_recursive():
    # "src/**/*.py" → -wholename '*/src/*/*.py' OR similar
    # Implementation: replace ** with * (find -wholename '*' matches multiple segments
    # because globstar isn't honored by find by default; we use -wholename which
    # matches the entire path against the shell glob, with * spanning segments).
    assert _glob_to_find_expr("src/**/*.py") == "-wholename '*/src/*/*.py'"
