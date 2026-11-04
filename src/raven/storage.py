from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raven.contracts import Item, SemanticVerdict, SourceBinding, WatchSpec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_state (
    watch_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    cursor TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (watch_id, source_key)
);

CREATE TABLE IF NOT EXISTS items (
    item_key TEXT PRIMARY KEY,
    item_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_item_state (
    watch_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    last_item_json TEXT NOT NULL,
    last_decision TEXT,
    last_confidence REAL,
    evaluated_input_hash TEXT,
    judge_summary_json TEXT,
    last_evaluated_at TEXT,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (watch_id, item_key)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    watch_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT
);

CREATE TABLE IF NOT EXISTS event_subscriptions (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    event_name TEXT NOT NULL,
    routing_key TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    callback_url TEXT NOT NULL,
    secret TEXT NOT NULL,
    refresh_before TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_deliveries (
    event_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_at TEXT,
    last_error TEXT,
    delivered_at TEXT,
    PRIMARY KEY (event_id, subscription_id)
);
"""


def item_key(item: Item) -> str:
    return f"{item.source_type}:{item.source_id}:{item.external_id}"


def source_key(source: SourceBinding) -> str:
    return f"{source.type}:{source.target}"


def fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class SQLiteStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def save_watch(self, watch: WatchSpec, owner: str, status: str = "active") -> None:
        if watch.id is None:
            raise ValueError("WatchSpec must have an id before it can be saved")

        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT owner, created_at FROM watches WHERE id = ?",
                (watch.id,),
            ).fetchone()
            if existing is not None and existing[0] != owner:
                raise PermissionError("Watch belongs to another owner")

            created_at = existing[1] if existing else now
            connection.execute(
                """
                INSERT INTO watches (id, owner, spec_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    spec_json = excluded.spec_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (watch.id, owner, watch.model_dump_json(), status, created_at, now),
            )

    def get_watch(self, watch_id: str, owner: str | None = None) -> WatchSpec | None:
        query = "SELECT spec_json FROM watches WHERE id = ?"
        params: list[Any] = [watch_id]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)

        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return WatchSpec.model_validate_json(row[0]) if row else None

    def get_watch_owner(self, watch_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner FROM watches WHERE id = ?",
                (watch_id,),
            ).fetchone()
        return row[0] if row else None

    def list_watches(
        self,
        status: str | None = None,
        owner: str | None = None,
    ) -> list[WatchSpec]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if owner is not None:
            clauses.append("owner = ?")
            params.append(owner)

        query = "SELECT spec_json FROM watches"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [WatchSpec.model_validate_json(row[0]) for row in rows]

    def set_watch_status(
        self,
        watch_id: str,
        status: str,
        owner: str | None = None,
    ) -> bool:
        query = "UPDATE watches SET status = ?, updated_at = ? WHERE id = ?"
        params: list[Any] = [status, _now(), watch_id]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)

        with self._connect() as connection:
            cursor = connection.execute(query, params)
        return cursor.rowcount > 0

    def get_source_cursor(self, watch_id: str, source: SourceBinding) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor FROM source_state WHERE watch_id = ? AND source_key = ?",
                (watch_id, source_key(source)),
            ).fetchone()
        return row[0] if row else None

    def set_source_cursor(self, watch_id: str, source: SourceBinding, cursor: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_state (watch_id, source_key, cursor, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(watch_id, source_key) DO UPDATE SET
                    cursor = excluded.cursor,
                    updated_at = excluded.updated_at
                """,
                (watch_id, source_key(source), cursor, _now()),
            )

    def store_item(self, item: Item) -> None:
        key = item_key(item)
        payload = item.model_dump(mode="json")
        content_hash = fingerprint(payload)
        now = _now()

        with self._connect() as connection:
            row = connection.execute(
                "SELECT first_seen_at FROM items WHERE item_key = ?",
                (key,),
            ).fetchone()
            first_seen_at = row[0] if row else now
            connection.execute(
                """
                INSERT INTO items (item_key, item_json, content_hash, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    item_json = excluded.item_json,
                    content_hash = excluded.content_hash,
                    last_seen_at = excluded.last_seen_at
                """,
                (key, json.dumps(payload), content_hash, first_seen_at, now),
            )

    def get_watch_item(self, watch_id: str, item: Item) -> Item | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_item_json
                FROM watch_item_state
                WHERE watch_id = ? AND item_key = ?
                """,
                (watch_id, item_key(item)),
            ).fetchone()
        return Item.model_validate_json(row[0]) if row else None

    def remember_watch_item(self, watch_id: str, item: Item) -> None:
        payload = item.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO watch_item_state (
                    watch_id, item_key, last_item_json, last_seen_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(watch_id, item_key) DO UPDATE SET
                    last_item_json = excluded.last_item_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (watch_id, item_key(item), json.dumps(payload), _now()),
            )

    def save_watch_item_evaluation(
        self,
        watch_id: str,
        item: Item,
        evaluated_input_hash: str,
        verdict: SemanticVerdict | None,
    ) -> None:
        summary = verdict.model_dump(mode="json") if verdict else None
        decision = verdict.decision if verdict else "pass"
        confidence = verdict.confidence if verdict else None

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE watch_item_state
                SET last_decision = ?,
                    last_confidence = ?,
                    evaluated_input_hash = ?,
                    judge_summary_json = ?,
                    last_evaluated_at = ?
                WHERE watch_id = ? AND item_key = ?
                """,
                (
                    decision,
                    confidence,
                    evaluated_input_hash,
                    json.dumps(summary) if summary is not None else None,
                    _now(),
                    watch_id,
                    item_key(item),
                ),
            )

    def get_evaluated_input_hash(self, watch_id: str, item: Item) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT evaluated_input_hash
                FROM watch_item_state
                WHERE watch_id = ? AND item_key = ?
                """,
                (watch_id, item_key(item)),
            ).fetchone()
        return row[0] if row else None

    def upsert_event_subscription(
        self,
        subscription_id: str,
        owner: str,
        event_name: str,
        routing_key: str,
        arguments_json: str,
        callback_url: str,
        secret: str,
        refresh_before: str | None,
    ) -> None:
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT owner, created_at FROM event_subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            if existing is not None and existing[0] != owner:
                raise PermissionError("Subscription belongs to another owner")

            created_at = existing[1] if existing else now
            connection.execute(
                """
                INSERT INTO event_subscriptions (
                    id, owner, event_name, routing_key, arguments_json,
                    callback_url, secret, refresh_before, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    secret = excluded.secret,
                    refresh_before = excluded.refresh_before,
                    updated_at = excluded.updated_at
                """,
                (
                    subscription_id,
                    owner,
                    event_name,
                    routing_key,
                    arguments_json,
                    callback_url,
                    secret,
                    refresh_before,
                    created_at,
                    now,
                ),
            )

    def remove_event_subscription(self, subscription_id: str, owner: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM event_subscriptions WHERE id = ? AND owner = ?",
                (subscription_id, owner),
            )
        return cursor.rowcount > 0

    def save_event(
        self,
        event_id: str,
        event_type: str,
        watch_id: str,
        payload_json: str,
        created_at: str,
    ) -> None:
        owner = self.get_watch_owner(watch_id)
        if owner is None:
            raise ValueError(f"Watch {watch_id!r} does not exist")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (
                    id, type, watch_id, owner, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, event_type, watch_id, owner, payload_json, created_at),
            )
            connection.execute(
                """
                INSERT INTO event_deliveries (
                    event_id, subscription_id, status, attempts
                )
                SELECT ?, id, 'pending', 0
                FROM event_subscriptions
                WHERE owner = ?
                  AND event_name = ?
                  AND routing_key = ?
                  AND (
                    refresh_before IS NULL
                    OR refresh_before > ?
                  )
                """,
                (event_id, owner, event_type, watch_id, created_at),
            )

    def get_event_payload(self, event_id: str, owner: str | None = None) -> str | None:
        query = "SELECT payload_json FROM events WHERE id = ?"
        params: list[Any] = [event_id]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)

        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return row[0] if row else None

    def list_pending_event_payloads(
        self,
        owner: str | None = None,
        limit: int = 50,
    ) -> list[str]:
        query = """
            SELECT payload_json
            FROM events
            WHERE acknowledged_at IS NULL
        """
        params: list[Any] = []
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row[0] for row in rows]

    def list_deliveries_due(
        self,
        now: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    events.payload_json,
                    event_deliveries.subscription_id,
                    event_deliveries.attempts,
                    event_subscriptions.callback_url,
                    event_subscriptions.secret
                FROM event_deliveries
                JOIN events ON events.id = event_deliveries.event_id
                JOIN event_subscriptions
                    ON event_subscriptions.id = event_deliveries.subscription_id
                WHERE event_deliveries.status IN ('pending', 'retry')
                  AND (
                    event_deliveries.next_attempt_at IS NULL
                    OR event_deliveries.next_attempt_at <= ?
                  )
                  AND (
                    event_subscriptions.refresh_before IS NULL
                    OR event_subscriptions.refresh_before > ?
                  )
                ORDER BY events.created_at ASC
                LIMIT ?
                """,
                (now, now, limit),
            ).fetchall()

        return [
            {
                "event_json": row[0],
                "subscription_id": row[1],
                "attempts": row[2],
                "callback_url": row[3],
                "secret": row[4],
            }
            for row in rows
        ]

    def mark_delivery_succeeded(
        self,
        event_id: str,
        subscription_id: str,
        delivered_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE event_deliveries
                SET status = 'delivered',
                    attempts = attempts + 1,
                    next_attempt_at = NULL,
                    last_error = NULL,
                    delivered_at = ?
                WHERE event_id = ? AND subscription_id = ?
                """,
                (delivered_at, event_id, subscription_id),
            )

    def mark_delivery_failed(
        self,
        event_id: str,
        subscription_id: str,
        error: str,
        next_attempt_at: str | None,
    ) -> None:
        status = "retry" if next_attempt_at is not None else "failed"
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE event_deliveries
                SET status = ?,
                    attempts = attempts + 1,
                    next_attempt_at = ?,
                    last_error = ?
                WHERE event_id = ? AND subscription_id = ?
                """,
                (
                    status,
                    next_attempt_at,
                    error,
                    event_id,
                    subscription_id,
                ),
            )

    def get_event_delivery_states(
        self,
        event_id: str,
        owner: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                event_deliveries.subscription_id,
                event_deliveries.status,
                event_deliveries.attempts,
                event_deliveries.next_attempt_at,
                event_deliveries.last_error,
                event_deliveries.delivered_at
            FROM event_deliveries
            JOIN events ON events.id = event_deliveries.event_id
            WHERE event_deliveries.event_id = ?
        """
        params: list[Any] = [event_id]
        if owner is not None:
            query += " AND events.owner = ?"
            params.append(owner)
        query += " ORDER BY event_deliveries.subscription_id"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [
            {
                "subscription_id": row[0],
                "status": row[1],
                "attempts": row[2],
                "next_attempt_at": row[3],
                "last_error": row[4],
                "delivered_at": row[5],
            }
            for row in rows
        ]

    def get_event_acknowledged_at(
        self,
        event_id: str,
        owner: str | None = None,
    ) -> str | None:
        query = "SELECT acknowledged_at FROM events WHERE id = ?"
        params: list[Any] = [event_id]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)

        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return row[0] if row else None

    def acknowledge_event(self, event_id: str, owner: str | None = None) -> bool:
        query = """
            UPDATE events
            SET acknowledged_at = ?
            WHERE id = ? AND acknowledged_at IS NULL
        """
        params: list[Any] = [_now(), event_id]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)

        with self._connect() as connection:
            cursor = connection.execute(query, params)
        return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def _now() -> str:
    return datetime.now(UTC).isoformat()
