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


class DeliveryStatus(BaseModel):
    subscription_id: str
    status: Literal["pending", "retry", "delivered", "failed"]
    attempts: int
    next_attempt_at: datetime | None = None
    last_error: str | None = None
    delivered_at: datetime | None = None


class EventStatus(BaseModel):
    event_id: str
    acknowledged_at: datetime | None = None
    deliveries: list[DeliveryStatus] = Field(default_factory=list)


class EventDispatcher(Protocol):
    async def publish(self, event: CandidateReadyEvent) -> None: ...


class OutboxEventDispatcher:
    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    async def publish(self, event: CandidateReadyEvent) -> None:
        self._storage.save_event(
            event_id=event.id,
            event_type=event.type,
            watch_id=event.watch_id,
            payload_json=event.model_dump_json(),
            created_at=event.created_at.isoformat(),
        )


def load_event(
    storage: SQLiteStorage,
    event_id: str,
    owner: str | None = None,
) -> CandidateReadyEvent | None:
    payload = storage.get_event_payload(event_id, owner)
    return CandidateReadyEvent.model_validate_json(payload) if payload else None


def load_pending_events(
    storage: SQLiteStorage,
    owner: str | None = None,
    limit: int = 50,
) -> list[CandidateReadyEvent]:
    return [
        CandidateReadyEvent.model_validate_json(payload)
        for payload in storage.list_pending_event_payloads(owner, limit)
    ]


def load_event_status(
    storage: SQLiteStorage,
    event_id: str,
    owner: str | None = None,
) -> EventStatus | None:
    if storage.get_event_payload(event_id, owner) is None:
        return None

    return EventStatus(
        event_id=event_id,
        acknowledged_at=storage.get_event_acknowledged_at(event_id, owner),
        deliveries=[
            DeliveryStatus.model_validate(state)
            for state in storage.get_event_delivery_states(event_id, owner)
        ],
    )
