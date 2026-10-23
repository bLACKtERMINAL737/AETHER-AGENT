import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
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



def test_rejecting_non_pending_proposal_is_a_conflict(monkeypatch):
    from fastapi import HTTPException
    import aether.app as app_module

    class AlreadyApprovedCoding:
        def reject(self, proposal_id):
            raise CodingError("only pending proposals can be rejected")

    monkeypatch.setattr(app_module, "coding", AlreadyApprovedCoding())

    with pytest.raises(HTTPException) as exc_info:
        app_module.reject_coding_proposal("proposal-123")

    assert exc_info.value.status_code == 409


def test_concurrent_approve_and_reject_only_allow_one_transition(tmp_path: Path, monkeypatch):
    engine, store, _source, proposal = make_proposal(tmp_path)
    original_get_proposal = store.get_proposal
    both_read_pending = threading.Barrier(2)
    thread_state = threading.local()

    def synchronized_get_proposal(proposal_id):
        result = original_get_proposal(proposal_id)
        # Force both operations to pass their initial pending-status check
        # before either attempts the conditional SQL status transition.
        if not getattr(thread_state, "initial_read_done", False):
            thread_state.initial_read_done = True
            if result is not None and result["status"] == "pending":
                both_read_pending.wait(timeout=5)
        return result

    monkeypatch.setattr(store, "get_proposal", synchronized_get_proposal)

    def decide(action):
        try:
            action(proposal["id"])
            return "success"
        except (CodingError, ValueError):
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        approve_future = executor.submit(decide, engine.approve)
        reject_future = executor.submit(decide, engine.reject)
        outcomes = [approve_future.result(timeout=10), reject_future.result(timeout=10)]

    assert outcomes.count("success") == 1
    assert outcomes.count("conflict") == 1
    saved = original_get_proposal(proposal["id"])
    assert saved is not None
    assert saved["status"] in {"approved", "rejected"}
