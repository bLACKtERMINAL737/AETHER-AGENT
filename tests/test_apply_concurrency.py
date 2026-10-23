"""Regression tests for cross-process coding apply serialization."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from aether.coding import CodingEngine, CodingError
from aether.store import TaskStore


class UnusedRouter:
    async def chat(self, message, task_type="general"):
        raise AssertionError("The router should not be used by apply tests")


def _engine(workspace: Path, db_path: Path) -> tuple[CodingEngine, TaskStore]:
    store = TaskStore(db_path)
    return CodingEngine(workspace, store, UnusedRouter()), store


def test_concurrent_apply_of_same_proposal_only_changes_file_once(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    original = "VALUE = 1\n"
    updated = "VALUE = 2\n"
    source.write_text(original, encoding="utf-8")
    db_path = tmp_path / "aether.sqlite3"

    first_engine, store = _engine(workspace, db_path)
    second_engine, _ = _engine(workspace, db_path)
    proposal = store.create_proposal("concurrent apply", [{
        "path": "sample.py",
        "original_content": original,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "content": updated,
        "diff": "",
    }])
    first_engine.approve(proposal["id"])

    start = Barrier(2)

    def apply(engine: CodingEngine) -> str:
        start.wait(timeout=5)
        try:
            engine.apply(proposal["id"])
            return "applied"
        except CodingError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(apply, (first_engine, second_engine)))

    assert outcomes.count("applied") == 1
    assert outcomes.count("rejected") == 1
    assert source.read_text(encoding="utf-8") == updated
    assert store.get_proposal(proposal["id"])["status"] == "applied"


def test_busy_apply_lock_prevents_startup_style_recovery_from_touching_proposal(
    tmp_path: Path,
):
    store = TaskStore(tmp_path / "aether.sqlite3")
    proposal = store.create_proposal("live apply", [])
    store.set_proposal_status(proposal["id"], "approved")
    assert store.claim_proposal_for_apply(proposal["id"]) is True

    with store.coding_apply_lock() as acquired:
        assert acquired is True
        with store.coding_apply_lock(blocking=False) as recovery_acquired:
            assert recovery_acquired is False
            # Startup recovery must be skipped while another process is applying.
            assert store.get_proposal(proposal["id"])["status"] == "applying"

    assert store.get_proposal(proposal["id"])["status"] == "applying"


def test_repeated_apply_after_success_is_rejected_without_rewriting_file(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    original = "VALUE = 1\n"
    updated = "VALUE = 2\n"
    source.write_text(original, encoding="utf-8")
    engine, store = _engine(workspace, tmp_path / "aether.sqlite3")
    proposal = store.create_proposal("apply once", [{
        "path": "sample.py",
        "original_content": original,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "content": updated,
        "diff": "",
    }])
    engine.approve(proposal["id"])

    engine.apply(proposal["id"])
    modified_at_first_apply = source.stat().st_mtime_ns

    with pytest.raises(CodingError, match="explicitly approved"):
        engine.apply(proposal["id"])

    assert source.read_text(encoding="utf-8") == updated
    assert source.stat().st_mtime_ns == modified_at_first_apply
    assert store.get_proposal(proposal["id"])["status"] == "applied"
