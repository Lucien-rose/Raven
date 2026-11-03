from __future__ import annotations

from raven.adapters.base import SourceAdapter
from raven.contracts import CandidateContext, WatchSpec
from raven.runtime import WatchRuntime
from raven.storage import SQLiteStorage


class WatchRunner:
    def __init__(
        self,
        storage: SQLiteStorage,
        adapters: dict[str, SourceAdapter],
        runtime: WatchRuntime,
    ) -> None:
        self._storage = storage
        self._adapters = adapters
        self._runtime = runtime

    async def run_once(self, watch: WatchSpec) -> list[CandidateContext]:
        if watch.id is None:
            raise ValueError("WatchSpec must have an id before it can run")

        candidates: list[CandidateContext] = []
        for source in watch.sources:
            adapter = self._adapters.get(source.type)
            if adapter is None:
                raise ValueError(f"No source adapter registered for {source.type!r}")

            cursor = self._storage.get_source_cursor(watch.id, source)
            batch = await adapter.fetch(source, cursor)
            if batch.cursor is not None:
                self._storage.set_source_cursor(watch.id, source, batch.cursor)

            for item in batch.items:
                previous = self._storage.store_item(item)
                candidate = await self._runtime.evaluate(watch, item, previous)
                if candidate is not None:
                    candidates.append(candidate)

        return candidates
