import json

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


def make_watch(watch_id: str = "watch-1") -> WatchSpec:
    return WatchSpec(
        id=watch_id,
        name="Test",
        original_intent="Watch something",
        sources=[],
    )


def make_event(watch_id: str = "watch-1") -> CandidateReadyEvent:
    item = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://example.test/1",
        title="Bug",
    )
    return CandidateReadyEvent(
        watch_id=watch_id,
        candidate=CandidateContext(
            watch_id=watch_id,
            watch_spec_version="1",
            item=item,
            diff={"_new": True},
            rule_result=RuleResult(passed=True, checks=[]),
        ),
    )


def test_storage_scopes_watches_to_owner(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    watch = make_watch()
    storage.save_watch(watch, owner="alice")

    assert storage.get_watch("watch-1", owner="alice") == watch
    assert storage.get_watch("watch-1", owner="bob") is None
    assert storage.list_watches(owner="alice") == [watch]
    assert storage.list_watches(owner="bob") == []


def test_storage_keeps_watch_item_state(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    storage.save_watch(make_watch(), owner="alice")

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
async def test_event_outbox_creates_one_delivery_per_matching_subscription(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    storage.save_watch(make_watch(), owner="alice")

    for suffix, watch_id in [("a", "watch-1"), ("b", "watch-1"), ("other", "watch-2")]:
        storage.upsert_event_subscription(
            subscription_id=f"sub-{suffix}",
            owner="alice",
            event_name="candidate.ready",
            routing_key=watch_id,
            arguments_json=json.dumps({"watch_id": watch_id}),
            callback_url=f"https://example.com/{suffix}",
            secret="whsec_test",
            refresh_before=None,
        )

    event = make_event()
    await OutboxEventDispatcher(storage).publish(event)

    assert load_event(storage, event.id, owner="alice") == event
    assert load_event(storage, event.id, owner="bob") is None
    assert load_pending_events(storage, owner="alice") == [event]

    status = load_event_status(storage, event.id, owner="alice")
    assert status is not None
    assert [delivery.subscription_id for delivery in status.deliveries] == [
        "sub-a",
        "sub-b",
    ]

    assert storage.acknowledge_event(event.id, owner="alice")
    assert load_pending_events(storage, owner="alice") == []
