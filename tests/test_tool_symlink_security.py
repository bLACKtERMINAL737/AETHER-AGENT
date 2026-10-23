from pathlib import Path

from aether.tools import ToolRegistry


def test_search_skips_symlinked_file_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("needle secret-value", encoding="utf-8")
    (workspace / "linked.txt").symlink_to(secret)

    result = ToolRegistry(workspace).execute("workspace.search_text", {"query": "needle"})

    assert result["matches"] == []


def test_search_does_not_traverse_symlinked_directory_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle secret-value", encoding="utf-8")
    (workspace / "linked-dir").symlink_to(outside, target_is_directory=True)

    result = ToolRegistry(workspace).execute("workspace.search_text", {"query": "needle"})

    assert result["matches"] == []


def test_search_reads_regular_workspace_file_with_descriptor_based_open(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("needle stays inside", encoding="utf-8")

    result = ToolRegistry(workspace).execute("workspace.search_text", {"query": "needle"})

    assert result["matches"] == [
        {"file": "notes.txt", "line": 1, "text": "needle stays inside"}
    ]


def test_search_skips_symlinked_file_even_when_nested_in_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "actual.txt"
    target.write_text("needle target", encoding="utf-8")
    (workspace / "alias.txt").symlink_to(target)

    result = ToolRegistry(workspace).execute("workspace.search_text", {"query": "needle"})

    assert [match["file"] for match in result["matches"]] == ["actual.txt"]
