from raven.contracts import Item, WatchSpec
from raven.events import CandidateReadyEvent
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


def test_storage_persists_and_acknowledges_events(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()

    watch = WatchSpec(
        id="watch-1",
        name="Test",
        original_intent="Watch something",
        sources=[],
    )
    item = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://example.test/1",
        title="Bug",
    )
    from raven.contracts import CandidateContext, RuleResult

    event = CandidateReadyEvent(
        watch_id="watch-1",
        candidate=CandidateContext(
            watch_id="watch-1",
            watch_spec_version=watch.version,
            item=item,
            diff={"_new": True},
            rule_result=RuleResult(passed=True, checks=[]),
        ),
    )

    storage.save_event(event)
    assert storage.list_pending_events() == [event]
    assert storage.acknowledge_event(event.id)
    assert storage.list_pending_events() == []
