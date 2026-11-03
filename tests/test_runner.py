import pytest

from raven.adapters.base import FetchBatch
from raven.contracts import HardRule, Item, RuleOperator, SourceBinding, WatchSpec
from raven.runner import WatchRunner
from raven.runtime import WatchRuntime
from raven.storage import SQLiteStorage


class FakeAdapter:
    def __init__(self, item: Item) -> None:
        self.item = item
        self.cursors: dict[str, str] = {}

    async def fetch(self, source: SourceBinding, cursor: str | None = None) -> FetchBatch:
        expected = self.cursors.get(source.target)
        if cursor is not None and cursor == expected:
            return FetchBatch(cursor=cursor)

        etag = f"etag:{source.target}"
        self.cursors[source.target] = etag
        return FetchBatch(items=[self.item], cursor=etag)


@pytest.mark.asyncio
async def test_runner_keeps_diff_state_per_watch(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()

    source = SourceBinding(type="github", target="owner/repo")
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

    watches = [
        WatchSpec(
            id=f"watch-{index}",
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
        for index in (1, 2)
    ]

    first = await runner.run_once(watches[0])
    second = await runner.run_once(watches[1])

    assert len(first) == 1
    assert len(second) == 1
    assert await runner.run_once(watches[0]) == []
    assert await runner.run_once(watches[1]) == []
