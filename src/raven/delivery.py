from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from raven.events import CandidateReadyEvent, EventTrigger, event_trigger
from raven.storage import SQLiteStorage

logger = logging.getLogger(__name__)


class EventTransport(Protocol):
    async def deliver(self, trigger: EventTrigger) -> None: ...


class WebhookEventTransport:
    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str,
        token: str | None = None,
    ) -> None:
        self._client = client
        self._url = url
        self._token = token

    async def deliver(self, trigger: EventTrigger) -> None:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        response = await self._client.post(
            self._url,
            headers=headers,
            json=trigger.model_dump(mode="json"),
        )
        response.raise_for_status()


class EventDeliveryWorker:
    def __init__(
        self,
        storage: SQLiteStorage,
        transport: EventTransport,
        poll_seconds: float = 1.0,
    ) -> None:
        self._storage = storage
        self._transport = transport
        self._poll_seconds = poll_seconds

    async def tick(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        for payload, attempts in self._storage.list_events_for_delivery(current.isoformat()):
            event = CandidateReadyEvent.model_validate_json(payload)
            try:
                await self._transport.deliver(event_trigger(event))
            except Exception as exc:
                next_attempt = current + timedelta(seconds=_retry_delay(attempts + 1))
                self._storage.mark_event_delivery_failed(
                    event.id,
                    next_attempt_at=next_attempt.isoformat(),
                    error=str(exc),
                )
                logger.warning("Event delivery failed for %s: %s", event.id, exc)
                continue

            self._storage.mark_event_delivered(event.id, delivered_at=current.isoformat())

    async def run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self._poll_seconds)


def _retry_delay(attempt: int) -> int:
    return min(5 * (2 ** max(attempt - 1, 0)), 300)
