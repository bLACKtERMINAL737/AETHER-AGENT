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
