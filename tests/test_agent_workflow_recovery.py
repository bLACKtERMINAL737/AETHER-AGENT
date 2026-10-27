import pytest
from fastapi import HTTPException

from aether import app as app_module
from aether.store import TaskStore


def make_workflow(tmp_path, monkeypatch, *, task_status="queued", qa=True):
    store = TaskStore(tmp_path / "recovery.sqlite3")
    monkeypatch.setattr(app_module, "store", store)
    task = store.create_task("[research] Inspect files", "Read-only inspection")
    if task_status != "queued":
        store.set_task_status(task["id"], task_status, error="saved state")
    results = {
        "tasks": [{
            "task_id": task["id"],
            "title": "Inspect files",
            "role": "research",
            "status": "queued" if task_status == "queued" else task_status,
        }],
        "qa_review": None,
    }
    if qa:
        qa_task = store.create_task("[qa_security] Review results", "Review saved results")
        results["qa_review"] = {"task_id": qa_task["id"], "status": "queued"}
    workflow = store.create_workflow("Inspect safely", [{"title": "Inspect files", "input": "Read-only inspection", "role": "research"}])
    store.update_workflow(workflow["id"], "unknown", results=results, error="simulated interruption")
    return store, workflow["id"], task["id"], results.get("qa_review", {}).get("task_id") if qa else None


@pytest.mark.asyncio
async def test_recovery_runs_only_checkpointed_queued_tasks(tmp_path, monkeypatch):
    store, workflow_id, task_id, qa_id = make_workflow(tmp_path, monkeypatch)
    executed = []

    async def fake_run(task_id_arg):
        task = store.get_task(task_id_arg)
        assert task is not None and task["status"] == "queued"
        assert store.claim_task(task_id_arg)
        store.set_task_status(task_id_arg, "succeeded", result={"answer": "verified"})
        executed.append(task_id_arg)
        return {"task_id": task_id_arg, "status": "succeeded", "result": "verified", "tool_calls": 0, "tool_attempts": 0}

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.recover_agent_workflow(workflow_id)

    assert result["status"] == "succeeded"
    assert set(executed) == {task_id, qa_id}
    saved = store.get_workflow(workflow_id)
    assert saved["status"] == "succeeded"
    assert saved["results"]["tasks"][0]["status"] == "succeeded"
    assert saved["results"]["qa_review"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_recovery_never_replays_unknown_task_and_marks_partial(tmp_path, monkeypatch):
    store, workflow_id, task_id, qa_id = make_workflow(
        tmp_path, monkeypatch, task_status="unknown"
    )
    executed = []

    async def fake_run(task_id_arg):
        task = store.get_task(task_id_arg)
        assert task is not None and task["status"] == "queued"
        assert store.claim_task(task_id_arg)
        store.set_task_status(task_id_arg, "succeeded", result={"answer": "reviewed"})
        executed.append(task_id_arg)
        return {"task_id": task_id_arg, "status": "succeeded", "result": "reviewed", "tool_calls": 0, "tool_attempts": 0}

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.recover_agent_workflow(workflow_id)

    assert task_id not in executed
    assert executed == [qa_id]
    assert result["status"] == "partial"
    assert store.get_task(task_id)["status"] == "unknown"
    assert store.get_workflow(workflow_id)["status"] == "partial"


@pytest.mark.asyncio
async def test_recovery_rejects_checkpoint_task_state_mismatch(tmp_path, monkeypatch):
    store, workflow_id, task_id, _qa_id = make_workflow(tmp_path, monkeypatch)
    store.set_task_status(task_id, "running")
    with pytest.raises(HTTPException) as error:
        await app_module.recover_agent_workflow(workflow_id)
    assert error.value.status_code == 409
    assert store.get_workflow(workflow_id)["status"] == "unknown"


def test_workflow_recovery_claim_is_atomic(tmp_path):
    store = TaskStore(tmp_path / "claim.sqlite3")
    workflow = store.create_workflow("Atomic claim", [])
    store.update_workflow(workflow["id"], "unknown", results={"tasks": [], "qa_review": None})

    assert store.claim_workflow_recovery(workflow["id"]) is True
    assert store.claim_workflow_recovery(workflow["id"]) is False
    assert store.get_workflow(workflow["id"])["status"] == "running"
