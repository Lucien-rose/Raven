from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
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


def load_pending_events(
    storage: SQLiteStorage,
    limit: int = 50,
) -> list[CandidateReadyEvent]:
    return [
        CandidateReadyEvent.model_validate_json(payload)
        for payload in storage.list_pending_event_payloads(limit)
    ]
