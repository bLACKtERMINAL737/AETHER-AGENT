from pathlib import Path
import pytest

from aether.coding import CodingEngine, CodingError
from aether.store import TaskStore


class FakeRouter:
    def __init__(self, answer):
        self.answer = answer
    async def chat(self, message, task_type="general"):
        return {"answer": self.answer, "route": "coding", "model": "fake", "fallback_used": False, "attempts": 1}


def make_engine(tmp_path: Path, answer: str):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    store = TaskStore(tmp_path / "aether.sqlite3")
    engine = CodingEngine(workspace, store, FakeRouter(answer))
    return engine, store, workspace, source


@pytest.mark.asyncio
async def test_proposal_is_pending_and_does_not_change_files(tmp_path: Path):
    answer = '{"summary":"change value","changes":[{"path":"sample.py","content":"def value():\n    return 2\n"}]}'
    engine, store, workspace, source = make_engine(tmp_path, answer)
    before = source.read_text(encoding="utf-8")
    proposal = await engine.propose("Change value to 2", ["sample.py"])
    assert proposal["status"] == "pending"
    assert source.read_text(encoding="utf-8") == before
    assert "return 2" in proposal["changes"][0]["diff"]


def test_cannot_apply_before_approval(tmp_path: Path):
    engine, store, workspace, source = make_engine(tmp_path, "{}")
    proposal = store.create_proposal("test", [{
        "path": "sample.py",
        "original_content": source.read_text(encoding="utf-8"),
        "original_sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
        "content": "def value():\n    return 2\n",
        "diff": "",
    }])
    with pytest.raises(CodingError, match="approved"):
        engine.apply(proposal["id"])
    assert "return 1" in source.read_text(encoding="utf-8")


def test_approved_proposal_applies_atomically_and_marks_applied(tmp_path: Path):
    engine, store, workspace, source = make_engine(tmp_path, "{}")
    original = source.read_text(encoding="utf-8")
    import hashlib
    proposal = store.create_proposal("test", [{
        "path": "sample.py",
        "original_content": original,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "content": "def value():\n    return 2\n",
        "diff": "",
    }])
    engine.approve(proposal["id"])
    result = engine.apply(proposal["id"])
    assert result["status"] == "applied"
    assert "return 2" in source.read_text(encoding="utf-8")
    assert store.get_proposal(proposal["id"])["status"] == "applied"


def test_apply_refuses_stale_proposal(tmp_path: Path):
    engine, store, workspace, source = make_engine(tmp_path, "{}")
    original = source.read_text(encoding="utf-8")
    import hashlib
    proposal = store.create_proposal("test", [{
        "path": "sample.py",
        "original_content": original,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "content": "def value():\n    return 2\n",
        "diff": "",
    }])
    engine.approve(proposal["id"])
    source.write_text("def value():\n    return 9\n", encoding="utf-8")
    with pytest.raises(CodingError, match="changed since proposal"):
        engine.apply(proposal["id"])
    assert "return 9" in source.read_text(encoding="utf-8")


def test_test_runner_is_disabled_by_default(tmp_path: Path):
    engine, _, _, _ = make_engine(tmp_path, "{}")
    with pytest.raises(CodingError, match="disabled"):
        engine.run_tests()
