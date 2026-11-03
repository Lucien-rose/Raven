from __future__ import annotations

from raven.adapters.base import SourceAdapter
from raven.contracts import CandidateContext, WatchSpec
from raven.runtime import WatchRuntime
from raven.storage import SQLiteStorage, fingerprint


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
                previous = self._storage.get_watch_item(watch.id, item)
                self._storage.store_item(item)

                candidate = await self._runtime.evaluate(watch, item, previous)
                self._storage.remember_watch_item(watch.id, item)

                if candidate is None:
                    continue

                evaluated_input_hash = fingerprint(
                    {
                        "watch": watch.model_dump(mode="json"),
                        "item": item.model_dump(mode="json"),
                        "diff": candidate.diff,
                    }
                )
                if self._storage.get_evaluated_input_hash(watch.id, item) == evaluated_input_hash:
                    continue

                self._storage.save_watch_item_evaluation(
                    watch.id,
                    item,
                    evaluated_input_hash,
                    candidate.semantic_verdict,
                )
                candidates.append(candidate)

        return candidates
