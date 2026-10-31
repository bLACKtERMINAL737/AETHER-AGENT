"""Ensure an external chmod during apply is not overwritten by staged content."""

import hashlib
import stat
from pathlib import Path

import pytest

import aether.coding as coding_module
from aether.coding import CodingEngine, CodingError
from aether.store import TaskStore


class _UnusedRouter:
    async def chat(self, message, task_type="general"):
        raise AssertionError("apply must not invoke the model router")


def test_apply_refuses_to_overwrite_permissions_changed_after_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.py"
    original = "VALUE = 1" + chr(10)
    proposed = "VALUE = 2" + chr(10)
    source.write_text(original, encoding="utf-8")
    source.chmod(0o640)

    store = TaskStore(tmp_path / "tasks.sqlite3")
    engine = CodingEngine(workspace, store, _UnusedRouter())
    proposal = store.create_proposal(
        "detect concurrent permission change",
        [{
            "path": "sample.py",
            "original_content": original,
            "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "content": proposed,
            "diff": "",
        }],
    )
    engine.approve(proposal["id"])

    real_replace = coding_module.os.replace
    changed = False

    def chmod_before_replace(src, dst):
        nonlocal changed
        if not changed:
            source.chmod(0o600)
            changed = True
        return real_replace(src, dst)

    monkeypatch.setattr(coding_module.os, "replace", chmod_before_replace)

    with pytest.raises(CodingError, match="permissions changed while proposal was being applied"):
        engine.apply(proposal["id"])

    assert source.read_text(encoding="utf-8") == original
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
    saved = store.get_proposal(proposal["id"])
    assert saved is not None
    assert saved["status"] == "approved"
    assert not list(workspace.glob(".aether-stage-*"))
