"""Cover uncertain rollback when directory durability sync fails."""

import hashlib
from pathlib import Path

import pytest

from aether.coding import CodingEngine, CodingError
from aether.store import TaskStore


class _UnusedRouter:
    async def chat(self, message, task_type="general"):
        raise AssertionError("apply must not invoke the model router")


def test_rollback_directory_sync_failure_keeps_proposal_in_applying_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    original = "VALUE = 1\\n"
    proposed = "VALUE = 2\\n"
    source.write_text(original, encoding="utf-8")

    store = TaskStore(tmp_path / "tasks.sqlite3")
    engine = CodingEngine(workspace, store, _UnusedRouter())
    proposal = store.create_proposal(
        "rollback durability failure",
        [{
            "path": "sample.py",
            "original_content": original,
            "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "content": proposed,
            "diff": "",
        }],
    )
    engine.approve(proposal["id"])

    sync_calls = 0

    def fail_apply_and_rollback_sync(_directory: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls in (1, 2):
            raise OSError(f"simulated directory fsync failure {sync_calls}")

    monkeypatch.setattr(engine, "_fsync_directory", fail_apply_and_rollback_sync)

    with pytest.raises(CodingError, match="rollback failure"):
        engine.apply(proposal["id"])

    # The rename rollback may have restored the bytes, but its durability was
    # not confirmed. The proposal must remain non-retryable pending inspection.
    assert source.read_text(encoding="utf-8") == original
    saved = store.get_proposal(proposal["id"])
    assert saved is not None
    assert saved["status"] == "applying"
    assert "rollback failure" in saved["error_text"]
    assert "simulated directory fsync failure 2" in saved["error_text"]
    assert not list(workspace.glob(".aether-stage-*"))
    assert not list(workspace.glob(".aether-rollback-*"))
