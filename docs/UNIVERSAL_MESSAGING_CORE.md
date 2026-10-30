# Universal Messaging Core

Maximu Agent's provider-neutral messaging contract is the foundation for a web inbox and optional channel adapters. It is not itself a connected social network integration.

## Contract

- Normalizes inbound messages into a provider-neutral, validated envelope.
- Defines outbound messages and explicit delivery states: accepted, sent, delivered, failed, unknown.
- Requires an explicit adapter registry; no dynamic plugin imports or automatic discovery of untrusted code.
- Derives an opaque session scope from deployment namespace, channel, and provider user ID to reduce accidental cross-channel/session collisions.
- Bounds message and identifier sizes and requires timezone-aware inbound timestamps.

## Adapter requirements

A concrete connector must implement ChannelAdapter.send and should also provide provider-specific webhook verification, authentication, rate limiting, retry policy, deduplication, and delivery-status reconciliation before being exposed to users. Never log access tokens or unfiltered provider payloads. Inbound user content is untrusted input, not instructions to change agent permissions or security policy.

## Platform support

The registry intentionally starts empty. Telegram, Discord, WhatsApp, Slack, email, and other platforms are roadmap targets, not enabled integrations. Each platform requires a supported API, user-granted permissions, credentials, and compliance with provider rules. Some platforms may not permit the desired automation or message types.

## Validation

Run `pytest -q tests/test_messaging.py`.

This suite tests the provider-neutral contract only. It does not prove delivery to any external messaging platform.
