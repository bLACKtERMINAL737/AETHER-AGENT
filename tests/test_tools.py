from pathlib import Path
import pytest
from aether.tools import ToolRegistry, ToolError, provider_tool_name


def test_list_and_search_workspace(tmp_path: Path):
    (tmp_path / "hello.py").write_text("print('hello')\n# Aether test\n", encoding="utf-8")
    registry = ToolRegistry(tmp_path)
    listing = registry.execute("workspace.list_files", {"path": "."})
    assert any(entry["name"] == "hello.py" for entry in listing["entries"])
    result = registry.execute("workspace.search_text", {"query": "Aether"})
    assert result["matches"][0]["file"] == "hello.py"


def test_path_escape_is_rejected(tmp_path: Path):
    registry = ToolRegistry(tmp_path / "workspace")
    with pytest.raises(ToolError):
        registry.execute("workspace.list_files", {"path": "../outside"})


def test_unknown_tool_is_rejected(tmp_path: Path):
    registry = ToolRegistry(tmp_path)
    with pytest.raises(ToolError):
        registry.execute("shell.run", {"command": "whoami"})


def test_provider_tool_names_are_valid_and_reversible(tmp_path: Path):
    registry = ToolRegistry(tmp_path)
    internal_names = [item["name"] for item in registry.describe()]
    exposed_names = [provider_tool_name(name) for name in internal_names]

    assert len(exposed_names) == len(set(exposed_names))
    assert all(name and len(name) <= 64 for name in exposed_names)
    assert all(all(char.isalnum() or char in "_-" for char in name) for name in exposed_names)
    assert dict(zip(exposed_names, internal_names)) == {
        provider_tool_name(name): name for name in internal_names
    }


def test_read_file_returns_real_contents(tmp_path: Path):
    source = tmp_path / "sample.py"
    source.write_text("first\nsecond\nthird\n", encoding="utf-8")
    registry = ToolRegistry(tmp_path)

    result = registry.execute(
        "workspace.read_file",
        {"path": "sample.py", "start_line": 2, "max_lines": 1},
    )

    assert result["path"] == "sample.py"
    assert result["content"] == "second"
    assert result["total_lines"] == 3
    assert result["truncated"] is True


def test_read_file_rejects_path_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("secret", encoding="utf-8")
    registry = ToolRegistry(workspace)

    with pytest.raises(ToolError):
        registry.execute("workspace.read_file", {"path": "../outside.py"})


def test_read_file_rejects_directory(tmp_path: Path):
    registry = ToolRegistry(tmp_path)
    with pytest.raises(ToolError):
        registry.execute("workspace.read_file", {"path": "."})


def test_workspace_tool_descriptions_distinguish_read_list_and_search(tmp_path: Path):
    registry = ToolRegistry(tmp_path)
    descriptions = {item["name"]: item["description"] for item in registry.describe()}

    assert "READ A SPECIFIC FILE" in descriptions["workspace.read_file"]
    assert "never guess contents" in descriptions["workspace.read_file"]
    assert "directory listing" in descriptions["workspace.list_files"]
    assert "not for reading a known file" in descriptions["workspace.search_text"]
