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
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    watch_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL
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

    def save_watch(self, watch: WatchSpec, status: str = "active") -> None:
        if watch.id is None:
            raise ValueError("WatchSpec must have an id before it can be saved")

        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM watches WHERE id = ?", (watch.id,)
            ).fetchone()
            created_at = existing[0] if existing else now
            connection.execute(
                """
                INSERT INTO watches (id, spec_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    spec_json = excluded.spec_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (watch.id, watch.model_dump_json(), status, created_at, now),
            )

    def get_watch(self, watch_id: str) -> WatchSpec | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT spec_json FROM watches WHERE id = ?", (watch_id,)
            ).fetchone()
        return WatchSpec.model_validate_json(row[0]) if row else None

    def list_watches(self, status: str | None = None) -> list[WatchSpec]:
        query = "SELECT spec_json FROM watches"
        params: tuple[Any, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [WatchSpec.model_validate_json(row[0]) for row in rows]

    def set_watch_status(self, watch_id: str, status: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE watches SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), watch_id),
            )
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
                "SELECT first_seen_at FROM items WHERE item_key = ?", (key,)
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

    def save_event(
        self,
        event_id: str,
        event_type: str,
        payload_json: str,
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, event_type, payload_json, created_at),
            )

    def list_pending_event_payloads(self, limit: int = 50) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM events
                WHERE acknowledged_at IS NULL
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def acknowledge_event(self, event_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE events
                SET acknowledged_at = ?
                WHERE id = ? AND acknowledged_at IS NULL
                """,
                (_now(), event_id),
            )
        return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def _now() -> str:
    return datetime.now(UTC).isoformat()
