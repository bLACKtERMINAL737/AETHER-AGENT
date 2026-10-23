import hashlib
from pathlib import Path

import pytest

from aether.coding import CodingEngine, CodingError
from aether.store import TaskStore


class UnusedRouter:
    async def chat(self, message, task_type="general"):
        raise AssertionError("These tests must not call the model router")


def make_proposal(tmp_path: Path, status: str = "pending"):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    original = "VALUE = 1\n"
    source.write_text(original, encoding="utf-8")
    store = TaskStore(tmp_path / "aether.sqlite3")
    engine = CodingEngine(workspace, store, UnusedRouter())
    proposal = store.create_proposal(
        "change value",
        [{
            "path": "sample.py",
            "original_content": original,
            "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "content": "VALUE = 2\n",
            "diff": "",
        }],
    )
    if status != "pending":
        store.set_proposal_status(proposal["id"], status)
    return engine, store, source, proposal


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_apply_never_changes_files_without_explicit_approval(
    tmp_path: Path, status: str
):
    engine, store, source, proposal = make_proposal(tmp_path, status=status)
    before = source.read_text(encoding="utf-8")

    with pytest.raises(CodingError, match="explicitly approved"):
        engine.apply(proposal["id"])

    assert source.read_text(encoding="utf-8") == before
    assert store.get_proposal(proposal["id"])["status"] == status


def test_applied_proposal_cannot_be_applied_a_second_time(tmp_path: Path):
    engine, store, source, proposal = make_proposal(tmp_path)
    engine.approve(proposal["id"])

    first_result = engine.apply(proposal["id"])
    assert first_result["status"] == "applied"
    applied_content = source.read_text(encoding="utf-8")
    assert applied_content == "VALUE = 2\n"

    with pytest.raises(CodingError, match="explicitly approved"):
        engine.apply(proposal["id"])

    assert source.read_text(encoding="utf-8") == applied_content
    assert store.get_proposal(proposal["id"])["status"] == "applied"
