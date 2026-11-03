import pytest

from raven.contracts import HardRule, Item, RuleOperator, WatchSpec
from raven.runtime import WatchRuntime


@pytest.mark.asyncio
async def test_runtime_ignores_unchanged_and_rejected_items() -> None:
    watch = WatchSpec(
        id="watch-1",
        name="Open issues",
        original_intent="Watch open issues",
        sources=[],
        hard_rules=[
            HardRule(
                id="open",
                field="metadata.state",
                operator=RuleOperator.EQUALS,
                value="open",
            )
        ],
    )
    runtime = WatchRuntime()
    open_item = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://example.test/1",
        title="Bug",
        metadata={"state": "open"},
    )

    assert await runtime.evaluate(watch, open_item, previous=open_item) is None

    closed_item = open_item.model_copy(update={"metadata": {"state": "closed"}})
    assert await runtime.evaluate(watch, closed_item) is None

    candidate = await runtime.evaluate(watch, open_item)
    assert candidate is not None
    assert candidate.diff == {"_new": True}
