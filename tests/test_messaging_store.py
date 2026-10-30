from pathlib import Path

import pytest

from aether.messaging_store import MessagingStore


def test_inbound_message_persists_and_deduplicates(tmp_path: Path):
    path = tmp_path / "inbox.sqlite3"
    store = MessagingStore(path)
    payload = dict(
        channel=" Telegram ", provider_message_id="msg-1", provider_user_id="user-secret",
        text="hello", received_at="2026-10-29T10:00:00+00:00", display_name="Alex",
    )
    first = store.ingest(**payload)
    second = store.ingest(**payload)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["conversation_id"] == second["conversation_id"]
    assert first["message"]["status"] == "accepted"
    reopened = MessagingStore(path)
    assert len(reopened.list_messages(first["conversation_id"])) == 1
    assert reopened.list_conversations()[0]["last_message"] == "hello"
    assert "user-secret" not in str(reopened.list_conversations())


def test_channels_are_isolated_and_provider_ids_not_persisted(tmp_path: Path):
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    a = store.ingest(channel="telegram", provider_message_id="1", provider_user_id="same-user", text="one")
    b = store.ingest(channel="discord", provider_message_id="1", provider_user_id="same-user", text="two")
    assert a["conversation_id"] != b["conversation_id"]
    with store.connect() as con:
        rows = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='messaging_conversations'").fetchone()
        assert "provider_user_id" not in rows["sql"]


def test_outbound_idempotency_and_conflict(tmp_path: Path):
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    kwargs = dict(channel="telegram", provider_user_id="u1", text="reply", idempotency_key="send-1")
    first = store.queue_outbound(**kwargs)
    second = store.queue_outbound(**kwargs)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    with pytest.raises(ValueError, match="different message"):
        store.queue_outbound(**{**kwargs, "text": "changed"})


@pytest.mark.parametrize("kwargs", [
    {"channel": "../telegram", "provider_message_id": "x", "provider_user_id": "u", "text": "hi"},
    {"channel": "telegram", "provider_message_id": "x", "provider_user_id": "u", "text": " "},
    {"channel": "telegram", "provider_message_id": "x", "provider_user_id": "", "text": "hi"},
])
def test_inbound_validation(tmp_path: Path, kwargs):
    with pytest.raises(ValueError):
        MessagingStore(tmp_path / "inbox.sqlite3").ingest(**kwargs)


def test_message_history_limit_is_bounded(tmp_path: Path):
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    result = store.ingest(channel="telegram", provider_message_id="x", provider_user_id="u", text="hi")
    with pytest.raises(ValueError):
        store.list_messages(result["conversation_id"], limit=201)



def test_outbound_delivery_status_is_persisted(tmp_path: Path):
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    result = store.queue_outbound(
        channel="telegram", provider_user_id="chat-1", text="hello", idempotency_key="send-1"
    )
    store.update_outbound_status(
        "telegram", "send-1", "sent", provider_message_id="telegram-message-9"
    )
    saved = store.get_outbound("telegram", "send-1")
    assert saved is not None
    assert saved["id"] == result["message"]["id"]
    assert saved["status"] == "sent"
    assert saved["provider_message_id"] == "telegram-message-9"


def test_outbound_delivery_status_rejects_invalid_value(tmp_path: Path):
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    with pytest.raises(ValueError, match="invalid outbound delivery status"):
        store.update_outbound_status("telegram", "missing", "accepted")



def test_delivery_target_is_encrypted_and_decryptable(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("AETHER_MESSAGING_TARGET_KEY", key)
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    queued = store.queue_outbound(
        channel="telegram", provider_user_id="chat-private", text="hello",
        idempotency_key="target-1", delivery_target="123456789",
    )
    assert store.get_delivery_target(queued["message"]["id"]) == "123456789"
    with store.connect() as con:
        raw = con.execute(
            "SELECT ciphertext FROM messaging_delivery_targets WHERE message_id=?",
            (queued["message"]["id"],),
        ).fetchone()["ciphertext"]
    assert b"123456789" not in bytes(raw)
    assert "ciphertext" not in queued["message"]


def test_delivery_target_is_not_persisted_without_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AETHER_MESSAGING_TARGET_KEY", raising=False)
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    queued = store.queue_outbound(
        channel="telegram", provider_user_id="chat-private", text="hello",
        idempotency_key="target-2", delivery_target="123456789",
    )
    assert store.get_delivery_target(queued["message"]["id"]) is None


def test_invalid_delivery_target_key_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AETHER_MESSAGING_TARGET_KEY", "not-a-fernet-key")
    with pytest.raises(ValueError, match="valid Fernet key"):
        MessagingStore(tmp_path / "inbox.sqlite3")



def test_outbox_claim_is_atomic_and_only_claims_target_backed_messages(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("AETHER_MESSAGING_TARGET_KEY", Fernet.generate_key().decode())
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    with_target = store.queue_outbound(
        channel="telegram", provider_user_id="u1", text="ready",
        idempotency_key="claim-1", delivery_target="123",
    )
    store.queue_outbound(
        channel="telegram", provider_user_id="u2", text="no target",
        idempotency_key="claim-2",
    )
    first = store.claim_outbound(worker_id="worker-a", limit=10, lease_seconds=30)
    second = store.claim_outbound(worker_id="worker-b", limit=10, lease_seconds=30)
    assert [item["id"] for item in first] == [with_target["message"]["id"]]
    assert second == []


def test_outbox_lease_requires_current_owner_and_finishes_once(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("AETHER_MESSAGING_TARGET_KEY", Fernet.generate_key().decode())
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    queued = store.queue_outbound(
        channel="telegram", provider_user_id="u1", text="ready",
        idempotency_key="claim-owner", delivery_target="123",
    )
    message_id = queued["message"]["id"]
    assert store.claim_outbound(worker_id="worker-a", lease_seconds=30)
    assert not store.finish_outbound_lease(message_id, worker_id="worker-b", status="sent")
    assert store.finish_outbound_lease(message_id, worker_id="worker-a", status="sent")
    assert not store.finish_outbound_lease(message_id, worker_id="worker-a", status="sent")
    assert store.get_outbound("telegram", "claim-owner")["status"] == "sent"


def test_expired_lease_becomes_unknown_not_automatically_requeued(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("AETHER_MESSAGING_TARGET_KEY", Fernet.generate_key().decode())
    store = MessagingStore(tmp_path / "inbox.sqlite3")
    queued = store.queue_outbound(
        channel="telegram", provider_user_id="u1", text="ready",
        idempotency_key="claim-expiry", delivery_target="123",
    )
    message_id = queued["message"]["id"]
    store.claim_outbound(worker_id="worker-a", lease_seconds=5)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store.connect() as con:
        con.execute("UPDATE messaging_delivery_leases SET lease_until=? WHERE message_id=?", (expired, message_id))
    assert store.expire_outbound_leases() == 1
    assert store.get_outbound("telegram", "claim-expiry")["status"] == "unknown"
    assert store.claim_outbound(worker_id="worker-b") == []



def test_rate_limit_retry_is_delayed_and_bounded(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("AETHER_MESSAGING_TARGET_KEY", Fernet.generate_key().decode())
    store = MessagingStore(tmp_path / "retry.sqlite3")
    queued = store.queue_outbound(
        channel="telegram", provider_user_id="u", text="hello",
        idempotency_key="retry-1", delivery_target="123",
    )
    message_id = queued["message"]["id"]
    assert store.claim_outbound(worker_id="w1")
    assert store.retry_outbound_lease(
        message_id, worker_id="w1", delay_seconds=30, max_retries=2
    ) == "scheduled"
    assert store.claim_outbound(worker_id="w2") == []
    with store.connect() as con:
        con.execute(
            "UPDATE messaging_delivery_retries SET next_attempt_at=? WHERE message_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), message_id),
        )
    assert store.claim_outbound(worker_id="w2")
    assert store.retry_outbound_lease(
        message_id, worker_id="w2", delay_seconds=1, max_retries=2
    ) == "scheduled"
    with store.connect() as con:
        con.execute(
            "UPDATE messaging_delivery_retries SET next_attempt_at=? WHERE message_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), message_id),
        )
    assert store.claim_outbound(worker_id="w3")
    assert store.retry_outbound_lease(
        message_id, worker_id="w3", delay_seconds=1, max_retries=2
    ) == "exhausted"
    assert store.get_outbound("telegram", "retry-1")["status"] == "failed"


def test_unknown_delivery_reconciliation_requires_evidence_and_is_audited(tmp_path: Path):
    store = MessagingStore(tmp_path / "reconcile.sqlite3")
    queued = store.queue_outbound(
        channel="telegram", provider_user_id="u", text="hello",
        idempotency_key="unknown-1",
    )
    store.update_outbound_status("telegram", "unknown-1", "unknown")
    message_id = queued["message"]["id"]
    with pytest.raises(ValueError, match="evidence"):
        store.reconcile_unknown(message_id, status="sent", evidence=" ")
    result = store.reconcile_unknown(
        message_id, status="sent", evidence="Confirmed in provider conversation",
        provider_message_id="provider-123",
    )
    assert result["status"] == "sent"
    saved = store.get_outbound("telegram", "unknown-1")
    assert saved["status"] == "sent"
    assert saved["provider_message_id"] == "provider-123"
    with store.connect() as con:
        audit = con.execute(
            "SELECT previous_status,new_status,evidence FROM messaging_delivery_reconciliations WHERE message_id=?",
            (message_id,),
        ).fetchone()
    assert tuple(audit) == ("unknown", "sent", "Confirmed in provider conversation")
    with pytest.raises(ValueError, match="only unknown"):
        store.reconcile_unknown(message_id, status="failed", evidence="Checked again")
