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
    answer = '{"summary":"change value","changes":[{"path":"sample.py","content":"def value():\\n    return 2\\n"}]}'
    engine, store, workspace, source = make_engine(tmp_path, answer)
    before = source.read_text(encoding="utf-8")
    proposal = await engine.propose("Change value to 2", ["sample.py"])
    assert proposal["status"] == "pending"
    assert source.read_text(encoding="utf-8") == before
    assert "return 2" in proposal["changes"][0]["diff"]



@pytest.mark.asyncio
async def test_proposal_rejects_unchanged_content(tmp_path: Path):
    answer = (
        '{"summary":"pretend change","changes":['
        '{"path":"sample.py","content":"def value():\\n    return 1\\n"}]}'
    )
    engine, store, workspace, source = make_engine(tmp_path, answer)
    before = source.read_text(encoding="utf-8")

    with pytest.raises(CodingError, match="no actual changes"):
        await engine.propose("Change value", ["sample.py"])

    assert source.read_text(encoding="utf-8") == before
    assert store.list_proposals() == []

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


def test_coding_engine_rejects_path_escape(tmp_path: Path):
    engine, _, _, _ = make_engine(tmp_path, "{}")
    with pytest.raises(CodingError, match="escapes"):
        engine.read_sources(["../outside.py"])


def test_coding_engine_rejects_symlink_paths(tmp_path: Path):
    engine, _, workspace, source = make_engine(tmp_path, "{}")
    linked = workspace / "linked.py"
    try:
        linked.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable in this environment")
    with pytest.raises(CodingError, match="Symlink"):
        engine.read_sources(["linked.py"])


@pytest.mark.asyncio
async def test_proposal_cannot_modify_unselected_file(tmp_path: Path):
    answer = '{"summary":"bad proposal","changes":[{"path":"other.py","content":"print(1)"}]}'
    engine, _, workspace, source = make_engine(tmp_path, answer)
    (workspace / "other.py").write_text("print(0)\n", encoding="utf-8")
    with pytest.raises(CodingError, match="unselected file"):
        await engine.propose("Change sample", ["sample.py"])


@pytest.mark.asyncio
async def test_iterative_loop_returns_pending_proposal_after_sandbox_pass(tmp_path: Path, monkeypatch):
    first = '{"summary":"first attempt","changes":[{"path":"sample.py","content":"def value():\\n    return 2\\n"}]}'
    second = '{"summary":"fixed attempt","changes":[{"path":"sample.py","content":"def value():\\n    return 3\\n"}]}'

    class SequenceRouter:
        def __init__(self):
            self.answers = [first, second]
            self.prompts = []
        async def chat(self, message, task_type="general"):
            self.prompts.append(message)
            return {"answer": self.answers.pop(0), "route": "coding", "model": "fake", "fallback_used": False, "attempts": 1}

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    original = "def value():\n    return 1\n"
    source.write_text(original, encoding="utf-8")
    store = TaskStore(tmp_path / "aether.sqlite3")
    router = SequenceRouter()
    engine = CodingEngine(workspace, store, router, enable_test_runner=True)

    results = iter([
        {"passed": False, "returncode": 1, "stdout": "assert 2 == 3", "stderr": ""},
        {"passed": True, "returncode": 0, "stdout": "2 passed", "stderr": ""},
    ])
    monkeypatch.setattr(CodingEngine, "run_tests", lambda self: next(results))

    outcome = await engine.iterate_with_tests("Make value correct", ["sample.py"], max_rounds=2)

    assert outcome["passed"] is True
    assert len(outcome["rounds"]) == 2
    assert outcome["proposal"]["status"] == "pending"
    assert "return 3" in outcome["proposal"]["changes"][0]["content"]
    assert source.read_text(encoding="utf-8") == original
    proposals = store.list_proposals()
    assert sum(p["status"] == "rejected" for p in proposals) == 2
    assert any("PREVIOUS SANDBOX TEST FAILURE" in prompt for prompt in router.prompts)


@pytest.mark.asyncio
async def test_iterative_loop_never_proposes_failed_candidate(tmp_path: Path, monkeypatch):
    answer = '{"summary":"bad attempt","changes":[{"path":"sample.py","content":"def value():\\n    return 2\\n"}]}'
    engine, store, workspace, source = make_engine(tmp_path, answer)
    engine.enable_test_runner = True
    monkeypatch.setattr(CodingEngine, "run_tests", lambda self: {
        "passed": False, "returncode": 1, "stdout": "", "stderr": "assertion failed"
    })

    outcome = await engine.iterate_with_tests("Try a change", ["sample.py"], max_rounds=1)

    assert outcome["passed"] is False
    assert outcome["proposal"] is None
    assert source.read_text(encoding="utf-8") == "def value():\n    return 1\n"
    assert all(p["status"] == "rejected" for p in store.list_proposals())


def test_proposal_store_round_trip(tmp_path: Path):
    store = TaskStore(tmp_path / "aether.sqlite3")
    created = store.create_proposal("summary", [{"path": "sample.py", "content": "print(1)"}])
    assert created["status"] == "pending"
    assert created["changes"][0]["path"] == "sample.py"
    store.set_proposal_status(created["id"], "approved")
    assert store.get_proposal(created["id"])["status"] == "approved"

@pytest.mark.asyncio
async def test_proposal_rejects_duplicate_paths(tmp_path: Path):
    answer = (
        '{"summary":"duplicate change","changes":['
        '{"path":"sample.py","content":"def value():\\n    return 2\\n"},'
        '{"path":"sample.py","content":"def value():\\n    return 3\\n"}]}'
    )
    engine, store, workspace, source = make_engine(tmp_path, answer)
    before = source.read_text(encoding="utf-8")

    with pytest.raises(CodingError, match="duplicate change"):
        await engine.propose("Change value", ["sample.py"])

    assert source.read_text(encoding="utf-8") == before
    assert store.list_proposals() == []


@pytest.mark.parametrize("status", ["approved", "rejected", "applied"])
def test_reject_only_allows_pending_proposals(tmp_path: Path, status: str):
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
    store.set_proposal_status(proposal["id"], status)

    with pytest.raises(CodingError, match="Only pending proposals can be rejected"):
        engine.reject(proposal["id"])

    assert store.get_proposal(proposal["id"])["status"] == status


def test_pending_proposal_can_be_rejected(tmp_path: Path):
    engine, store, _, _ = make_engine(tmp_path, "{}")
    proposal = store.create_proposal("test", [{"path": "sample.py", "content": "print(1)"}])

    result = engine.reject(proposal["id"])

    assert result["status"] == "rejected"
