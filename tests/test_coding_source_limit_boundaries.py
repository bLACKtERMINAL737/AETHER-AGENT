from pathlib import Path

import pytest

from aether.coding import CodingEngine, CodingError
from aether.store import TaskStore


class FakeRouter:
    async def chat(self, message, task_type="general"):
        return {
            "answer": "{}",
            "route": "coding",
            "model": "fake",
            "fallback_used": False,
            "attempts": 1,
        }


def make_engine(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("VALUE = 1\\n", encoding="utf-8")
    return CodingEngine(workspace, TaskStore(tmp_path / "aether.sqlite3"), FakeRouter()), workspace


def test_read_sources_rejects_duplicate_paths(tmp_path: Path):
    engine, _ = make_engine(tmp_path)

    with pytest.raises(CodingError, match="Duplicate file paths"):
        engine.read_sources(["sample.py", "sample.py"])


def test_read_sources_rejects_too_many_files(tmp_path: Path):
    engine, workspace = make_engine(tmp_path)
    paths = []
    for index in range(engine.MAX_FILES + 1):
        name = f"file_{index}.py"
        (workspace / name).write_text("VALUE = 1\\n", encoding="utf-8")
        paths.append(name)

    with pytest.raises(CodingError, match="Select between 1 and"):
        engine.read_sources(paths)


def test_read_sources_rejects_oversized_file(tmp_path: Path):
    engine, workspace = make_engine(tmp_path)
    source = workspace / "large.py"
    source.write_text("x" * (engine.MAX_FILE_BYTES + 1), encoding="utf-8")

    with pytest.raises(CodingError, match="File is too large"):
        engine.read_sources(["large.py"])


def test_read_sources_rejects_non_utf8_source(tmp_path: Path):
    engine, workspace = make_engine(tmp_path)
    (workspace / "binary.py").write_bytes(bytes([86, 65, 76, 85, 69, 32, 61, 32, 255]))

    with pytest.raises(CodingError, match="File is not UTF-8 text"):
        engine.read_sources(["binary.py"])
