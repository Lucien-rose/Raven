import pytest

from raven.adapters.base import FetchBatch
from raven.contracts import HardRule, Item, RuleOperator, SourceBinding, WatchSpec
from raven.runner import WatchRunner
from raven.runtime import WatchRuntime
from raven.storage import SQLiteStorage


class FakeAdapter:
    def __init__(self, item: Item) -> None:
        self.item = item
        self.cursors: list[str | None] = []

    async def fetch(self, source: SourceBinding, cursor: str | None = None) -> FetchBatch:
        self.cursors.append(cursor)
        if cursor is not None:
            return FetchBatch(cursor=cursor)
        return FetchBatch(items=[self.item], cursor="etag-1")


@pytest.mark.asyncio
async def test_runner_persists_source_cursor_and_returns_candidate_once(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()

    source = SourceBinding(type="github", target="owner/repo")
    watch = WatchSpec(
        id="watch-1",
        name="Fresh open issues",
        original_intent="Watch fresh open issues",
        sources=[source],
        hard_rules=[
            HardRule(
                id="open",
                field="metadata.state",
                operator=RuleOperator.EQUALS,
                value="open",
            )
        ],
    )
    item = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://github.com/owner/repo/issues/1",
        title="Bug",
        metadata={"state": "open"},
    )
    adapter = FakeAdapter(item)
    runner = WatchRunner(storage, {"github": adapter}, WatchRuntime())

    first = await runner.run_once(watch)
    second = await runner.run_once(watch)

    assert len(first) == 1
    assert second == []
    assert adapter.cursors == [None, "etag-1"]
