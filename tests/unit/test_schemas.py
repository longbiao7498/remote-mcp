import json
from remote_mcp.schemas import ALL_TOOL_SCHEMAS


def test_all_thirteen_tools_have_schemas():
    expected = {
        "Read", "Write", "Edit", "MultiEdit", "MultiRead", "FileStat",
        "Bash", "Glob", "Grep", "Feedback",
        "Upload", "Download", "RemoteInfo",
    }
    assert set(ALL_TOOL_SCHEMAS.keys()) == expected


def test_required_lists_for_new_tools():
    assert set(ALL_TOOL_SCHEMAS["Upload"]["required"]) == {"local_path", "remote_path"}
    assert set(ALL_TOOL_SCHEMAS["Download"]["required"]) == {"remote_path", "local_path"}
    assert ALL_TOOL_SCHEMAS["RemoteInfo"]["required"] == []  # no params


def test_each_schema_has_required_keys():
    for name, schema in ALL_TOOL_SCHEMAS.items():
        assert "type" in schema, name
        assert schema["type"] == "object"
        assert "properties" in schema, name


def test_required_lists_are_correct():
    assert "file_path" in ALL_TOOL_SCHEMAS["Read"]["required"]
    assert set(ALL_TOOL_SCHEMAS["Edit"]["required"]) == {"file_path", "old_string", "new_string"}
    assert "command" in ALL_TOOL_SCHEMAS["Bash"]["required"]
    assert set(ALL_TOOL_SCHEMAS["Feedback"]["required"]) == {"category", "summary"}


def test_schemas_are_json_serializable():
    for name, schema in ALL_TOOL_SCHEMAS.items():
        json.dumps(schema)  # must not raise
