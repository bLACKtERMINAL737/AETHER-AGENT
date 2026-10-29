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
