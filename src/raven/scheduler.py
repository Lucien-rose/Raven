from __future__ import annotations

import asyncio
import logging
from time import monotonic

from raven.events import CandidateReadyEvent, EventDispatcher
from raven.runner import WatchRunner
from raven.storage import SQLiteStorage

logger = logging.getLogger(__name__)


class WatchScheduler:
    def __init__(
        self,
        storage: SQLiteStorage,
        runner: WatchRunner,
        dispatcher: EventDispatcher,
        poll_seconds: float = 1.0,
    ) -> None:
        self._storage = storage
        self._runner = runner
        self._dispatcher = dispatcher
        self._poll_seconds = poll_seconds
        self._next_due: dict[str, float] = {}

    async def tick(self, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        watches = self._storage.list_watches(status="active")
        active_ids = {watch.id for watch in watches if watch.id is not None}

        for watch_id in tuple(self._next_due):
            if watch_id not in active_ids:
                self._next_due.pop(watch_id, None)

        for watch in watches:
            if watch.id is None:
                continue

            due_at = self._next_due.get(watch.id, current)
            if current < due_at:
                continue

            self._next_due[watch.id] = current + watch.schedule.interval_seconds

            try:
                candidates = await self._runner.run_once(watch)
            except Exception:
                logger.exception("Watch %s failed", watch.id)
                continue

            for candidate in candidates:
                await self._dispatcher.publish(
                    CandidateReadyEvent(
                        watch_id=watch.id,
                        candidate=candidate,
                    )
                )

    async def run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self._poll_seconds)
