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
