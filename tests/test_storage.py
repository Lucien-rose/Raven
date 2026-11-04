import pytest

from raven.contracts import CandidateContext, Item, RuleResult, WatchSpec
from raven.events import (
    CandidateReadyEvent,
    OutboxEventDispatcher,
    load_event,
    load_event_status,
    load_pending_events,
)
from raven.storage import SQLiteStorage


def test_storage_keeps_current_watch_and_watch_item_state(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()

    watch = WatchSpec(
        id="watch-1",
        name="Test",
        original_intent="Watch something",
        sources=[],
    )
    storage.save_watch(watch)

    assert storage.get_watch("watch-1") == watch
    assert storage.list_watches() == [watch]

    first = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://example.test/1",
        title="Before",
    )
    updated = first.model_copy(update={"title": "After"})

    assert storage.get_watch_item("watch-1", first) is None
    storage.store_item(first)
    storage.remember_watch_item("watch-1", first)
    assert storage.get_watch_item("watch-1", updated) == first

    storage.store_item(updated)
    storage.remember_watch_item("watch-1", updated)
    assert storage.get_watch_item("watch-1", updated) == updated


@pytest.mark.asyncio
async def test_event_outbox_persists_and_acknowledges_events(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()

    item = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://example.test/1",
        title="Bug",
    )
    event = CandidateReadyEvent(
        watch_id="watch-1",
        candidate=CandidateContext(
            watch_id="watch-1",
            watch_spec_version="1",
            item=item,
            diff={"_new": True},
            rule_result=RuleResult(passed=True, checks=[]),
        ),
    )

    dispatcher = OutboxEventDispatcher(storage)
    await dispatcher.publish(event)

    assert load_event(storage, event.id) == event
    assert load_pending_events(storage) == [event]

    status = load_event_status(storage, event.id)
    assert status is not None
    assert status.delivery == "pending"
    assert status.attempts == 0

    assert storage.acknowledge_event(event.id)
    assert load_pending_events(storage) == []
    assert load_event_status(storage, event.id).acknowledged_at is not None
