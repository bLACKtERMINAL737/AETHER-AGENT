"""Startup recovery must respect the cross-process coding-apply lock."""

import asyncio
from contextlib import contextmanager

import pytest

import aether.app as app_module


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


from aether.store import TaskStore


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
