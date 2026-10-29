from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from aether import app as app_module
from aether.messaging_store import MessagingStore


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.content = b"present" if body is not None else b""

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._body


class FakeAsyncClient:
    calls = []
    response = FakeResponse()

    def __init__(self, *args, **kwargs):
        self.options = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.fixture
def isolated_store(monkeypatch, tmp_path: Path):
    store = MessagingStore(tmp_path / "messaging.sqlite3")
    monkeypatch.setattr(app_module, "messaging_store", store)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse(200, {"id": "discord-msg-1"})
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    return store


def test_discord_webhook_url_accepts_only_expected_https_hosts(monkeypatch):
    monkeypatch.setenv(
        "AETHER_DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123456/secret-token",
    )
    assert app_module._discord_webhook_url() == "https://discord.com/api/webhooks/123456/secret-token"

    for invalid in (
        "http://discord.com/api/webhooks/123456/token",
        "https://example.com/api/webhooks/123456/token",
        "https://discord.com.evil.example/api/webhooks/123456/token",
        "https://user:pass@discord.com/api/webhooks/123456/token",
        "https://discord.com/not-a-webhook",
    ):
        monkeypatch.setenv("AETHER_DISCORD_WEBHOOK_URL", invalid)
        assert app_module._discord_webhook_url() == ""


@pytest.mark.asyncio
async def test_discord_send_persists_provider_message_id(monkeypatch, isolated_store):
    monkeypatch.setenv(
        "AETHER_DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123456/secret-token",
    )
    result = await app_module.discord_send(
        app_module.DiscordSendRequest(text="hello", idempotency_key="send-1")
    )
    assert result["message"]["status"] == "sent"
    assert result["message"]["provider_message_id"] == "discord-msg-1"
    assert FakeAsyncClient.calls[0][1]["params"] == {"wait": "true"}
    assert isolated_store.get_outbound("discord", "send-1")["status"] == "sent"


@pytest.mark.asyncio
async def test_discord_send_rejects_unconfigured_destination(monkeypatch, isolated_store):
    monkeypatch.delenv("AETHER_DISCORD_WEBHOOK_URL", raising=False)
    with pytest.raises(HTTPException) as error:
        await app_module.discord_send(
            app_module.DiscordSendRequest(text="hello", idempotency_key="send-2")
        )
    assert error.value.status_code == 503
    assert FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_discord_send_does_not_retry_unknown_idempotency_key(monkeypatch, isolated_store):
    monkeypatch.setenv(
        "AETHER_DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123456/secret-token",
    )

    class BrokenClient(FakeAsyncClient):
        async def post(self, url, **kwargs):
            raise httpx.ConnectError("connection dropped")

    monkeypatch.setattr(app_module.httpx, "AsyncClient", BrokenClient)
    request = app_module.DiscordSendRequest(text="hello", idempotency_key="same-key")
    with pytest.raises(HTTPException) as first_error:
        await app_module.discord_send(request)
    assert first_error.value.status_code == 502
    assert isolated_store.get_outbound("discord", "same-key")["status"] == "unknown"
    call_count = len(FakeAsyncClient.calls)

    with pytest.raises(HTTPException) as retry_error:
        await app_module.discord_send(request)
    assert retry_error.value.status_code == 409
    assert len(FakeAsyncClient.calls) == call_count


@pytest.mark.asyncio
async def test_discord_send_marks_transport_failure_unknown(monkeypatch, isolated_store):
    monkeypatch.setenv(
        "AETHER_DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123456/secret-token",
    )

    class BrokenClient(FakeAsyncClient):
        async def post(self, url, **kwargs):
            raise httpx.ConnectError("connection dropped")

    monkeypatch.setattr(app_module.httpx, "AsyncClient", BrokenClient)
    with pytest.raises(HTTPException) as error:
        await app_module.discord_send(
            app_module.DiscordSendRequest(text="hello", idempotency_key="send-3")
        )
    assert error.value.status_code == 502
    assert isolated_store.get_outbound("discord", "send-3")["status"] == "unknown"
