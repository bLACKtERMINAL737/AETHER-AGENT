"""Persistent provider-neutral inbox storage.

Provider IDs are converted to opaque conversation scopes and are not persisted.
External adapters must verify webhook signatures before calling inbound APIs.
"""
from __future__ import annotations

import os
import re
import sqlite3

from cryptography.fernet import Fernet, InvalidToken
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .messaging import MAX_ID_CHARS, MAX_TEXT_CHARS, MessagingContractError, conversation_scope

_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_CONVERSATION_RE = re.compile(r"^msg_[a-f0-9]{40}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_channel(value: str) -> str:
    if not isinstance(value, str):
        raise MessagingContractError("channel must be text")
    channel = value.strip().lower()
    if not _CHANNEL_RE.fullmatch(channel):
        raise MessagingContractError("channel is invalid")
    return channel


def _validate_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_CHARS:
        raise MessagingContractError("message text must be non-empty and within the size limit")
    return value.strip()


class MessagingStore:
    """SQLite inbox/outbox journal sharing the application's database file."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS messaging_conversations (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    display_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_msg_conversations_updated
                    ON messaging_conversations(updated_at DESC);
                CREATE TABLE IF NOT EXISTS messaging_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES messaging_conversations(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
                    text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('accepted','sent','delivered','failed','unknown')),
                    provider_message_id TEXT,
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(channel, provider_message_id),
                    UNIQUE(channel, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_msg_messages_conversation
                    ON messaging_messages(conversation_id, created_at, id);
                CREATE TABLE IF NOT EXISTS messaging_delivery_targets (
                    message_id TEXT PRIMARY KEY REFERENCES messaging_messages(id) ON DELETE CASCADE,
                    ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messaging_delivery_leases (
                    message_id TEXT PRIMARY KEY REFERENCES messaging_messages(id) ON DELETE CASCADE,
                    lease_owner TEXT NOT NULL,
                    lease_until TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_msg_delivery_leases_until
                    ON messaging_delivery_leases(lease_until);
            """)
        raw_key = os.getenv("AETHER_MESSAGING_TARGET_KEY", "").strip()
        self._target_cipher = None
        if raw_key:
            try:
                self._target_cipher = Fernet(raw_key.encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise ValueError("AETHER_MESSAGING_TARGET_KEY must be a valid Fernet key") from exc

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    @staticmethod
    def _scope(channel: str, provider_user_id: str) -> str:
        if not isinstance(provider_user_id, str) or not provider_user_id.strip() or len(provider_user_id) > MAX_ID_CHARS:
            raise MessagingContractError("provider_user_id is invalid")
        namespace = "aether-claw"
        return conversation_scope(channel, provider_user_id, namespace=namespace)

    def ingest(
        self, *, channel: str, provider_message_id: str, provider_user_id: str,
        text: str, received_at: str | None = None, display_name: str | None = None,
    ) -> dict:
        channel = _validate_channel(channel)
        text = _validate_text(text)
        if not isinstance(provider_message_id, str) or not provider_message_id.strip() or len(provider_message_id) > MAX_ID_CHARS:
            raise MessagingContractError("provider_message_id is invalid")
        provider_message_id = provider_message_id.strip()
        if received_at is None:
            received_at = _now()
        try:
            parsed = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except (AttributeError, ValueError) as exc:
            raise MessagingContractError("received_at must be an ISO-8601 timestamp with timezone") from exc
        if display_name is not None:
            if not isinstance(display_name, str) or len(display_name) > 200:
                raise MessagingContractError("display_name is invalid")
            display_name = display_name.strip() or None
        conversation_id = self._scope(channel, provider_user_id)
        now = _now()
        with self.connect() as con:
            con.execute(
                "INSERT INTO messaging_conversations(id,channel,display_name,created_at,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET display_name=COALESCE(excluded.display_name,messaging_conversations.display_name), updated_at=excluded.updated_at",
                (conversation_id, channel, display_name, now, now),
            )
            existing = con.execute(
                "SELECT * FROM messaging_messages WHERE channel=? AND provider_message_id=?",
                (channel, provider_message_id),
            ).fetchone()
            if existing:
                return {"conversation_id": conversation_id, "message": dict(existing), "duplicate": True}
            message_id = str(uuid4())
            con.execute(
                "INSERT INTO messaging_messages(id,conversation_id,channel,direction,text,status,provider_message_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (message_id, conversation_id, channel, "inbound", text, "accepted", provider_message_id, received_at, now),
            )
            row = con.execute("SELECT * FROM messaging_messages WHERE id=?", (message_id,)).fetchone()
        return {"conversation_id": conversation_id, "message": dict(row), "duplicate": False}

    def queue_outbound(
        self, *, channel: str, provider_user_id: str, text: str,
        idempotency_key: str, delivery_target: str | None = None,
    ) -> dict:
        channel = _validate_channel(channel)
        text = _validate_text(text)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > MAX_ID_CHARS:
            raise MessagingContractError("idempotency_key is invalid")
        idempotency_key = idempotency_key.strip()
        if delivery_target is not None:
            if not isinstance(delivery_target, str) or not delivery_target.strip() or len(delivery_target) > MAX_ID_CHARS:
                raise MessagingContractError("delivery_target is invalid")
            delivery_target = delivery_target.strip()
        encrypted_target = (
            self._target_cipher.encrypt(delivery_target.encode("utf-8"))
            if delivery_target is not None and self._target_cipher is not None else None
        )
        conversation_id = self._scope(channel, provider_user_id)
        now = _now()
        with self.connect() as con:
            con.execute(
                "INSERT INTO messaging_conversations(id,channel,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at",
                (conversation_id, channel, now, now),
            )
            existing = con.execute(
                "SELECT * FROM messaging_messages WHERE channel=? AND idempotency_key=?",
                (channel, idempotency_key),
            ).fetchone()
            if existing:
                if existing["conversation_id"] != conversation_id or existing["text"] != text:
                    raise MessagingContractError("idempotency_key was already used for a different message")
                return {"conversation_id": conversation_id, "message": dict(existing), "duplicate": True}
            message_id = str(uuid4())
            con.execute(
                "INSERT INTO messaging_messages(id,conversation_id,channel,direction,text,status,idempotency_key,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (message_id, conversation_id, channel, "outbound", text, "accepted", idempotency_key, now, now),
            )
            if encrypted_target is not None:
                con.execute(
                    "INSERT INTO messaging_delivery_targets(message_id,ciphertext,created_at) VALUES(?,?,?)",
                    (message_id, encrypted_target, now),
                )
            row = con.execute("SELECT * FROM messaging_messages WHERE id=?", (message_id,)).fetchone()
        return {"conversation_id": conversation_id, "message": dict(row), "duplicate": False}

    def get_delivery_target(self, message_id: str) -> str | None:
        """Decrypt a delivery target for trusted backend workers; never include it in API message views."""
        if self._target_cipher is None:
            return None
        with self.connect() as con:
            row = con.execute(
                "SELECT ciphertext FROM messaging_delivery_targets WHERE message_id=?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return self._target_cipher.decrypt(bytes(row["ciphertext"])).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            return None

    def claim_outbound(
        self, *, worker_id: str, limit: int = 10, lease_seconds: int = 60,
    ) -> list[dict]:
        """Atomically lease eligible, target-backed outbound messages for one worker."""
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise MessagingContractError("worker_id is invalid")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not 5 <= lease_seconds <= 900:
            raise ValueError("lease_seconds must be between 5 and 900")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        claimed: list[dict] = []
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                """SELECT m.* FROM messaging_messages m
                   JOIN messaging_delivery_targets t ON t.message_id=m.id
                   LEFT JOIN messaging_delivery_leases l ON l.message_id=m.id
                   WHERE m.direction='outbound' AND m.status='accepted'
                     AND (l.message_id IS NULL OR l.lease_until < ?)
                   ORDER BY m.created_at, m.id LIMIT ?""",
                (now, limit),
            ).fetchall()
            for row in rows:
                con.execute(
                    """INSERT INTO messaging_delivery_leases(message_id,lease_owner,lease_until,attempts,updated_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(message_id) DO UPDATE SET
                         lease_owner=excluded.lease_owner,
                         lease_until=excluded.lease_until,
                         attempts=messaging_delivery_leases.attempts+1,
                         updated_at=excluded.updated_at""",
                    (row["id"], worker_id.strip(), lease_until, 1, now),
                )
                claimed.append({**dict(row), "lease_owner": worker_id.strip(),
                                "lease_until": lease_until})
        return claimed

    def finish_outbound_lease(
        self, message_id: str, *, worker_id: str, status: str,
        provider_message_id: str | None = None,
    ) -> bool:
        """Finish a lease only for its current owner; never auto-requeue uncertain outcomes."""
        if status not in {"sent", "delivered", "failed", "unknown"}:
            raise MessagingContractError("invalid outbound delivery status")
        now = _now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            lease = con.execute(
                "SELECT lease_owner FROM messaging_delivery_leases WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if lease is None or lease["lease_owner"] != worker_id:
                return False
            con.execute(
                """UPDATE messaging_messages SET status=?,
                   provider_message_id=COALESCE(?,provider_message_id), updated_at=?
                   WHERE id=? AND direction='outbound' AND status='accepted'""",
                (status, provider_message_id, now, message_id),
            )
            changed = con.execute("SELECT changes()").fetchone()[0] == 1
            if changed:
                con.execute("DELETE FROM messaging_delivery_leases WHERE message_id=?", (message_id,))
            return changed

    def expire_outbound_leases(self) -> int:
        """Mark expired in-flight claims unknown; explicit reconciliation is required before retry."""
        now = _now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                """SELECT message_id FROM messaging_delivery_leases
                   WHERE lease_until < ?""", (now,)
            ).fetchall()
            ids = [row["message_id"] for row in rows]
            for message_id in ids:
                con.execute(
                    """UPDATE messaging_messages SET status='unknown', updated_at=?
                       WHERE id=? AND direction='outbound' AND status='accepted'""",
                    (now, message_id),
                )
                con.execute("DELETE FROM messaging_delivery_leases WHERE message_id=?", (message_id,))
        return len(ids)

    def update_outbound_status(
        self, channel: str, idempotency_key: str, status: str,
        *, provider_message_id: str | None = None,
    ) -> None:
        if status not in {"sent", "delivered", "failed", "unknown"}:
            raise MessagingContractError("invalid outbound delivery status")
        with self.connect() as con:
            con.execute(
                "UPDATE messaging_messages SET status=?, provider_message_id=COALESCE(?, provider_message_id), updated_at=? "
                "WHERE channel=? AND idempotency_key=? AND direction='outbound'",
                (status, provider_message_id, _now(), channel, idempotency_key),
            )

    def get_outbound(self, channel: str, idempotency_key: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM messaging_messages WHERE channel=? AND idempotency_key=? AND direction='outbound'",
                (channel, idempotency_key),
            ).fetchone()
        return dict(row) if row else None

    def list_conversations(self, *, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self.connect() as con:
            rows = con.execute(
                """SELECT c.id, c.channel, c.display_name, c.created_at, c.updated_at,
                          (SELECT m.text FROM messaging_messages m WHERE m.conversation_id=c.id
                           ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message,
                          (SELECT m.direction FROM messaging_messages m WHERE m.conversation_id=c.id
                           ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_direction,
                          (SELECT m.status FROM messaging_messages m WHERE m.conversation_id=c.id
                           ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_status
                   FROM messaging_conversations c ORDER BY c.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_messages(self, conversation_id: str, *, limit: int = 100) -> list[dict]:
        if not isinstance(conversation_id, str) or not _CONVERSATION_RE.fullmatch(conversation_id):
            raise MessagingContractError("conversation ID is invalid")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM messaging_messages WHERE conversation_id=? ORDER BY created_at, id LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delivery_metrics(self) -> dict:
        """Return aggregate outbound delivery counts without exposing message content or IDs."""
        with self.connect() as con:
            totals = con.execute(
                """SELECT status, COUNT(*) AS count
                   FROM messaging_messages
                   WHERE direction='outbound'
                   GROUP BY status"""
            ).fetchall()
            channels = con.execute(
                """SELECT channel, status, COUNT(*) AS count
                   FROM messaging_messages
                   WHERE direction='outbound'
                   GROUP BY channel, status
                   ORDER BY channel, status"""
            ).fetchall()
            recent_failures = con.execute(
                """SELECT channel, status, COUNT(*) AS count, MAX(updated_at) AS latest_at
                   FROM messaging_messages
                   WHERE direction='outbound' AND status IN ('failed','unknown')
                   GROUP BY channel, status
                   ORDER BY latest_at DESC"""
            ).fetchall()
        by_status = {row["status"]: row["count"] for row in totals}
        for status in ("accepted", "sent", "delivered", "failed", "unknown"):
            by_status.setdefault(status, 0)
        by_channel: dict[str, dict[str, int]] = {}
        for row in channels:
            by_channel.setdefault(row["channel"], {})[row["status"]] = row["count"]
        for counts in by_channel.values():
            for status in ("accepted", "sent", "delivered", "failed", "unknown"):
                counts.setdefault(status, 0)
        return {
            "total_outbound": sum(by_status.values()),
            "by_status": by_status,
            "by_channel": by_channel,
            "recent_failures": [dict(row) for row in recent_failures[:20]],
        }

    def list_channels(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute("SELECT DISTINCT channel FROM messaging_conversations ORDER BY channel").fetchall()
        return [row["channel"] for row in rows]
