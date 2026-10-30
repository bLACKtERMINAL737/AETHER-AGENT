from fastapi.testclient import TestClient

import aether.app as app_module
from aether.scheduler_store import SchedulerStore


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_API_TOKEN", "test-token")
    monkeypatch.setattr(app_module, "scheduler_store", SchedulerStore(tmp_path / "scheduler.sqlite3"))
    return TestClient(app_module.app, raise_server_exceptions=False)


def auth():
    return {"X-Aether-Token": "test-token"}


def payload(**overrides):
    value = {
        "title": "Prepare weekly report",
        "input": "Summarize the project updates",
        "run_at": "2026-11-01T10:00:00+00:00",
        "idempotency_key": "weekly-report-1",
    }
    value.update(overrides)
    return value


def test_create_and_read_schedule_hides_internal_lease_and_idempotency_fields(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    created = client.post("/scheduler/schedules", json=payload(), headers=auth())
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "scheduled"
    assert item["title"] == "Prepare weekly report"
    assert "idempotency_key" not in item
    assert "lease_owner" not in item

    fetched = client.get(f"/scheduler/schedules/{item['id']}", headers=auth())
    assert fetched.status_code == 200
    assert fetched.json()["id"] == item["id"]


def test_create_is_idempotent_and_conflicting_key_is_rejected(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    first = client.post("/scheduler/schedules", json=payload(), headers=auth())
    second = client.post("/scheduler/schedules", json=payload(), headers=auth())
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    conflict = client.post(
        "/scheduler/schedules",
        json=payload(title="Different schedule"),
        headers=auth(),
    )
    assert conflict.status_code == 422


def test_schedule_requires_timezone_aware_run_at(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    response = client.post(
        "/scheduler/schedules",
        json=payload(run_at="2026-11-01T10:00:00"),
        headers=auth(),
    )
    assert response.status_code == 422


def test_list_limit_and_missing_schedule_errors(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    assert client.get("/scheduler/schedules?limit=201", headers=auth()).status_code == 400
    assert client.get("/scheduler/schedules/missing", headers=auth()).status_code == 404
    assert client.get("/scheduler/schedules", headers=auth()).json() == {"schedules": []}


def test_cancel_pending_schedule_and_reject_second_cancel(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    created = client.post("/scheduler/schedules", json=payload(), headers=auth())
    schedule_id = created.json()["id"]

    cancelled = client.delete(f"/scheduler/schedules/{schedule_id}", headers=auth())
    assert cancelled.status_code == 200
    assert cancelled.json() == {"id": schedule_id, "status": "cancelled"}
    assert client.delete(f"/scheduler/schedules/{schedule_id}", headers=auth()).status_code == 409
    assert client.delete("/scheduler/schedules/missing", headers=auth()).status_code == 404


def test_scheduler_routes_require_api_token(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    response = client.get("/scheduler/schedules")
    assert response.status_code == 401
