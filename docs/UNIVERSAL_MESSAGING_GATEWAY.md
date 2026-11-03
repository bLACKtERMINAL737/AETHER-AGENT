# Shared inbound messaging gateway

Crows uses a provider-neutral inbound dispatch boundary:

1. A provider connector authenticates and validates its own webhook or interaction.
2. The connector normalizes the event into the persistent messaging inbox.
3. Channel-to-session routing selects an isolated conversation session.
4. The durable dispatch journal records the normalized message and session route.
5. The shared inbound agent worker applies an explicit channel reply policy, loads
   bounded session history, and invokes the same tool-free model path.
6. The worker persists the turn and queues a deterministic-idempotency outbound
   message. The shared outbox handles provider delivery.

## Inbound reply policy registry

`crows.messaging_gateway.InboundChannelRegistry` is an explicit allowlist.
The built-in registry currently enables Telegram (4,096-character replies) and
Discord (2,000-character replies). A policy supplies a channel key, safe display
label, and maximum reply size. Unknown channels fail closed before a model call.
The registry never imports connector code dynamically.

A new channel needs all of the following before it is production-ready:
- a provider-specific authentication and normalization adapter;
- durable inbox and channel-scoped session routing;
- an explicit inbound reply policy;
- a provider-specific outbound transport and delivery-status mapping;
- tests for idempotency, ordering, isolation, failure, and uncertain delivery.

Registering a reply policy alone does not enable a provider integration. In
particular, it does not create a webhook endpoint or outbound transport.

## Safety and delivery semantics

Inbound content and conversation history are untrusted. The shared agent worker
has no tool registry, workspace, shell, browser, coding, or arbitrary action
capabilities. It does not claim to perform external actions.

The dispatch journal serializes work within each channel/conversation. Expired
leases become `unknown` and are not automatically replayed. A dispatch marked
`completed` means a reply was generated and durably queued, not that the
provider confirmed delivery. Inspect the outbound journal for delivery status.

## Current connector coverage

- Telegram: verified text webhook, inbox persistence, session routing, optional
  autonomous tool-free replies, and outbound bot messages.
- Discord: signed slash-command interactions, inbox persistence, session routing,
  optional autonomous tool-free replies, and deferred private response updates.
- Other platforms: no production inbound or outbound connector is implied.


## Shared outbound transport registry

The durable outbox worker dispatches through an explicit
`OutboundTransportRegistry`. Telegram and Discord are registered as concrete
transports; channel-specific HTTP methods, payloads, response parsing, and
Discord interaction-target validation live inside their adapters. The worker
retains responsibility for leases, retry scheduling, delivery-state
persistence, and uncertain-outcome handling. A 429 response is retried within
the existing bounded policy; network/response-decoding uncertainty remains
`unknown` and is never automatically replayed.

This registry currently contains only the Telegram and Discord transports.
Registering a future adapter does not by itself add its inbound webhook,
authentication, session-routing, or channel policy integration.
