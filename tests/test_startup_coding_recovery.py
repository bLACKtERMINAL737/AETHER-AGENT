"""Startup recovery must respect the cross-process coding-apply lock."""

import asyncio
from contextlib import contextmanager

import pytest

import crows.app as app_module


class StartupRecoveryStore:
    def __init__(self, *, lock_acquired: bool):
        self.lock_acquired = lock_acquired
        self.unknown_recovery_calls = 0
        self.proposal_recovery_calls = 0
        self.lock_blocking_arguments = []

    def mark_interrupted_as_unknown(self):
        self.unknown_recovery_calls += 1
        return 0

    @contextmanager
    def coding_apply_lock(self, *, blocking=True):
        self.lock_blocking_arguments.append(blocking)
        yield self.lock_acquired

    def mark_interrupted_proposals_for_review(self):
        self.proposal_recovery_calls += 1
        return 0


@pytest.mark.parametrize(
    ("lock_acquired", "expected_proposal_recovery_calls"),
    [(True, 1), (False, 0)],
)
def test_startup_recovery_only_runs_when_apply_lock_is_acquired(
    monkeypatch, lock_acquired, expected_proposal_recovery_calls
):
    fake_store = StartupRecoveryStore(lock_acquired=lock_acquired)
    monkeypatch.setattr(app_module, "store", fake_store)
    monkeypatch.setenv("CROWS_MESSAGING_WORKER_ENABLED", "false")
    monkeypatch.setenv("CROWS_SCHEDULER_WORKER_ENABLED", "false")

    async def start_and_stop_application():
        async with app_module.lifespan(app_module.app):
            pass

    asyncio.run(start_and_stop_application())

    assert fake_store.unknown_recovery_calls == 1
    assert fake_store.lock_blocking_arguments == [False]
    assert fake_store.proposal_recovery_calls == expected_proposal_recovery_calls


from crows.store import TaskStore


def make_applying_proposal(store: TaskStore) -> str:
    proposal = store.create_proposal(
        "startup recovery integration",
        [{"path": "sample.py", "content": "VALUE = 2\\n"}],
    )
    store.set_proposal_status(proposal["id"], "approved")
    assert store.claim_proposal_for_apply(proposal["id"]) is True
    return proposal["id"]


def run_application_startup(monkeypatch, store: TaskStore) -> None:
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setenv("CROWS_MESSAGING_WORKER_ENABLED", "false")
    monkeypatch.setenv("CROWS_SCHEDULER_WORKER_ENABLED", "false")

    async def start_and_stop_application():
        async with app_module.lifespan(app_module.app):
            pass

    asyncio.run(start_and_stop_application())


def test_startup_marks_real_interrupted_proposal_for_manual_review(
    tmp_path, monkeypatch
):
    store = TaskStore(tmp_path / "startup.sqlite3")
    proposal_id = make_applying_proposal(store)

    run_application_startup(monkeypatch, store)

    recovered = store.get_proposal(proposal_id)
    assert recovered["status"] == "applying"
    assert "Process restarted while applying" in recovered["error_text"]


def test_startup_does_not_recover_proposal_while_real_apply_lock_is_held(
    tmp_path, monkeypatch
):
    store = TaskStore(tmp_path / "startup-lock.sqlite3")
    proposal_id = make_applying_proposal(store)

    with store.coding_apply_lock() as acquired:
        assert acquired is True
        run_application_startup(monkeypatch, store)

    unchanged = store.get_proposal(proposal_id)
    assert unchanged["status"] == "applying"
    assert unchanged["error_text"] is None

    # Once the live owner releases the lock, a subsequent startup can recover it.
    run_application_startup(monkeypatch, store)
    recovered = store.get_proposal(proposal_id)
    assert recovered["status"] == "applying"
    assert "Process restarted while applying" in recovered["error_text"]



def test_process_crash_is_reconciled_by_next_application_startup(
    tmp_path, monkeypatch
):
    import subprocess
    import sys
    from pathlib import Path

    db_path = tmp_path / "hard-crash.sqlite3"
    child = """
import os
import sys
from pathlib import Path
from crows.store import TaskStore

store = TaskStore(Path(sys.argv[1]))
task = store.create_task("Interrupted specialist", "must not be replayed")
assert store.claim_task(task["id"])
store.begin_tool(task["id"], "external.write", {"value": "uncertain"})
workflow = store.create_workflow(
    "Interrupted workflow",
    [{"title": "Interrupted specialist", "input": "must not be replayed", "role": "research"}],
)
store.update_workflow(
    workflow["id"],
    "running",
    results={
        "tasks": [{"task_id": task["id"], "status": "running"}],
        "qa_review": None,
    },
)
# Simulate an abrupt process death: no application shutdown hooks run.
os._exit(23)
"""
    process = subprocess.run(
        [sys.executable, "-c", child, str(db_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 23, process.stderr

    # A fresh application process opens the same durable database and runs
    # its real FastAPI lifespan startup recovery.
    store = TaskStore(db_path)
    monkeypatch.setenv("CROWS_MESSAGING_WORKER_ENABLED", "false")
    monkeypatch.setenv("CROWS_SCHEDULER_WORKER_ENABLED", "false")
    monkeypatch.setattr(app_module, "store", store)
    run_application_startup(monkeypatch, store)

    tasks = store.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "unknown"
    tools = store.list_tool_executions(task["id"])
    assert len(tools) == 1
    assert tools[0]["status"] == "unknown"

    workflows = store.list_workflows()
    assert len(workflows) == 1
    assert workflows[0]["status"] == "unknown"
    assert workflows[0]["results"]["tasks"][0]["status"] == "running"

    # A second application startup must be a no-op for already-reconciled
    # records: no duplicate journal entries, timestamp churn, or lost checkpoints.
    task_before = task.copy()
    tools_before = [entry.copy() for entry in tools]
    workflow_before = workflows[0].copy()

    run_application_startup(monkeypatch, store)

    assert store.list_tasks() == [task_before]
    assert store.list_tool_executions(task["id"]) == tools_before
    assert store.list_workflows() == [workflow_before]
    assert store.mark_interrupted_as_unknown() == 0
