from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from aether.scheduler_store import SchedulerStore


def test_schedule_persists_across_reopen_and_normalizes_timezone(tmp_path: Path):
    path = tmp_path / "scheduler.sqlite3"
    due = datetime(2026, 11, 1, 12, tzinfo=timezone(timedelta(hours=2)))
    saved = SchedulerStore(path).create_schedule("Daily report", "Summarize updates", due, "report-1")
    reopened = SchedulerStore(path).get_schedule(saved["id"])
    assert reopened["status"] == "scheduled"
    assert reopened["run_at"] == "2026-11-01T10:00:00+00:00"


def test_idempotency_returns_same_schedule_and_rejects_conflicting_payload(tmp_path: Path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    first = store.create_schedule("One", "Do one", "2026-11-01T10:00:00+00:00", "same-key")
    second = store.create_schedule("One", "Do one", "2026-11-01T10:00:00+00:00", "same-key")
    assert first["id"] == second["id"]
    with pytest.raises(ValueError, match="different schedule"):
        store.create_schedule("Other", "Do other", "2026-11-01T10:00:00+00:00", "same-key")


def test_claim_due_is_atomic_across_store_instances(tmp_path: Path):
    path = tmp_path / "scheduler.sqlite3"
    first, second = SchedulerStore(path), SchedulerStore(path)
    first.create_schedule("Due", "Run", "2026-01-01T00:00:00+00:00", "due-1")
    now = "2026-01-02T00:00:00+00:00"
    claims_a = first.claim_due("worker-a", now=now)
    claims_b = second.claim_due("worker-b", now=now)
    assert len(claims_a) == 1
    assert claims_b == []
    assert claims_a[0]["lease_owner"] == "worker-a"


def test_only_lease_owner_can_finish_and_expired_lease_is_unknown(tmp_path: Path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    item = store.create_schedule("Due", "Run", "2026-01-01T00:00:00+00:00", "due-1")
    store.claim_due("worker-a", now="2026-01-02T00:00:00+00:00", lease_seconds=10)
    assert not store.finish_claim(item["id"], "worker-b", "completed", now="2026-01-02T00:00:05+00:00")
    assert not store.finish_claim(item["id"], "worker-a", "completed", now="2026-01-02T00:00:11+00:00")
    assert store.mark_expired_claims_unknown(now="2026-01-02T00:00:11+00:00") == 1
    saved = store.get_schedule(item["id"])
    assert saved["status"] == "unknown"
    assert saved["lease_owner"] is None


def test_cancel_only_affects_pending_schedules(tmp_path: Path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    item = store.create_schedule("Later", "Run", "2027-01-01T00:00:00+00:00", "later-1")
    assert store.cancel_schedule(item["id"]) is True
    assert store.cancel_schedule(item["id"]) is False
    assert store.get_schedule(item["id"])["status"] == "cancelled"


def test_schedule_rejects_naive_timestamps_and_invalid_limits(tmp_path: Path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    with pytest.raises(ValueError, match="timezone"):
        store.create_schedule("No timezone", "Run", "2026-11-01T10:00:00", "naive")
    with pytest.raises(ValueError, match="limit"):
        store.list_schedules(0)
    with pytest.raises(ValueError, match="worker_id"):
        store.claim_due(" ")


def test_renew_claim_extends_only_current_unexpired_owner_lease(tmp_path):
    store = SchedulerStore(tmp_path / "renew.sqlite3")
    schedule = store.create_schedule(
        "[research] Renew lease", "Check lease ownership",
        "2026-11-01T10:00:00+00:00", "renew-lease-1"
    )
    claimed = store.claim_due(
        "worker-a", now="2026-11-01T10:01:00+00:00", lease_seconds=60
    )
    assert len(claimed) == 1
    assert store.renew_claim(
        schedule["id"], "worker-a", now="2026-11-01T10:01:30+00:00", lease_seconds=300
    ) is True
    renewed = store.get_schedule(schedule["id"])
    assert renewed["lease_expires_at"] == "2026-11-01T10:06:30+00:00"
    assert store.renew_claim(
        schedule["id"], "worker-b", now="2026-11-01T10:01:31+00:00"
    ) is False


def test_renew_claim_rejects_expired_lease_and_invalid_duration(tmp_path):
    store = SchedulerStore(tmp_path / "expired-renew.sqlite3")
    schedule = store.create_schedule(
        "[research] Expired lease", "Check expired lease",
        "2026-11-01T10:00:00+00:00", "renew-lease-2"
    )
    store.claim_due("worker-a", now="2026-11-01T10:01:00+00:00", lease_seconds=10)
    assert store.renew_claim(
        schedule["id"], "worker-a", now="2026-11-01T10:01:11+00:00"
    ) is False
    with pytest.raises(ValueError):
        store.renew_claim(schedule["id"], "worker-a", lease_seconds=0)
