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
