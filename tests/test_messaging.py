from __future__ import annotations

import pytest

from aether.messaging import (
    ChannelRegistry,
    DeliveryReceipt,
    DeliveryStatus,
    InboundMessage,
    MessagingContractError,
    OutboundMessage,
    conversation_scope,
)


def inbound(**overrides):
    values = {
        "channel": "telegram",
        "provider_message_id": "provider-msg-1",
        "provider_user_id": "user-42",
        "text": "  Hello AETHER CLAW  ",
        "received_at": "2026-10-29T12:00:00+00:00",
    }
    values.update(overrides)
    return InboundMessage(**values)


def test_inbound_normalizes_channel_and_text():
    message = inbound(channel=" Telegram ")
    assert message.channel == "telegram"
    assert message.text == "Hello AETHER CLAW"


@pytest.mark.parametrize("values", [
    {"channel": "../telegram"},
    {"channel": "Telegram"},
    {"provider_message_id": ""},
    {"provider_user_id": " "},
    {"text": "  "},
    {"received_at": "not-a-date"},
    {"received_at": "2026-10-29T12:00:00"},
])
def test_inbound_rejects_invalid_fields(values):
    with pytest.raises(MessagingContractError):
        inbound(**values)


def test_inbound_rejects_oversized_text():
    with pytest.raises(MessagingContractError, match="exceeds"):
        inbound(text="x" * 20_001)


def test_outbound_rejects_empty_or_oversized_fields():
    with pytest.raises(MessagingContractError):
        OutboundMessage("telegram", "user", " ", "key")
    with pytest.raises(MessagingContractError):
        OutboundMessage("telegram", "user", "hello", "x" * 257)


def test_registry_is_explicit_and_duplicate_safe():
    class Adapter:
        channel_name = "telegram"

        async def send(self, message):
            return DeliveryReceipt("telegram", DeliveryStatus.SENT)

    registry = ChannelRegistry()
    assert registry.list_channels() == []
    registry.register(Adapter())
    assert registry.list_channels() == ["telegram"]
    assert registry.get("telegram").channel_name == "telegram"
    with pytest.raises(MessagingContractError, match="already registered"):
        registry.register(Adapter())
    with pytest.raises(MessagingContractError, match="not configured"):
        registry.get("whatsapp")


def test_delivery_receipt_has_timestamp_and_bounded_errors():
    receipt = DeliveryReceipt("discord", DeliveryStatus.UNKNOWN, error_code="provider_timeout")
    assert receipt.updated_at
    with pytest.raises(MessagingContractError):
        DeliveryReceipt("discord", DeliveryStatus.FAILED, error_code="x" * 101)


def test_conversation_scope_is_stable_and_channel_isolated():
    first = conversation_scope("telegram", "user-42", namespace="workspace-a")
    assert first == conversation_scope("telegram", "user-42", namespace="workspace-a")
    assert first != conversation_scope("discord", "user-42", namespace="workspace-a")
    assert first != conversation_scope("telegram", "user-42", namespace="workspace-b")
    assert first.startswith("msg_")
    assert "user-42" not in first
