from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from raven.contracts import CandidateContext

if TYPE_CHECKING:
    from raven.storage import SQLiteStorage


class CandidateReadyEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = "candidate.ready"
    watch_id: str
    candidate: CandidateContext
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EventTrigger(BaseModel):
    event_id: str
    type: str
    watch_id: str
    created_at: datetime


class EventStatus(BaseModel):
    event_id: str
    delivery: Literal["pending", "retry", "delivered"]
    attempts: int
    next_attempt_at: datetime | None = None
    last_error: str | None = None
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None


class EventDispatcher(Protocol):
    async def publish(self, event: CandidateReadyEvent) -> None: ...


class OutboxEventDispatcher:
    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    async def publish(self, event: CandidateReadyEvent) -> None:
        self._storage.save_event(
            event_id=event.id,
            event_type=event.type,
            payload_json=event.model_dump_json(),
            created_at=event.created_at.isoformat(),
        )


def load_event(storage: SQLiteStorage, event_id: str) -> CandidateReadyEvent | None:
    payload = storage.get_event_payload(event_id)
    return CandidateReadyEvent.model_validate_json(payload) if payload else None


def load_pending_events(
    storage: SQLiteStorage,
    limit: int = 50,
) -> list[CandidateReadyEvent]:
    return [
        CandidateReadyEvent.model_validate_json(payload)
        for payload in storage.list_pending_event_payloads(limit)
    ]


def load_event_status(storage: SQLiteStorage, event_id: str) -> EventStatus | None:
    state = storage.get_event_delivery_state(event_id)
    return EventStatus.model_validate(state) if state else None


def event_trigger(event: CandidateReadyEvent) -> EventTrigger:
    return EventTrigger(
        event_id=event.id,
        type=event.type,
        watch_id=event.watch_id,
        created_at=event.created_at,
    )
