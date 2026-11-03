from raven.contracts import Item, WatchSpec
from raven.storage import SQLiteStorage


def test_storage_keeps_current_watch_and_item_state(tmp_path) -> None:
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

    assert storage.store_item(first) is None
    assert storage.store_item(updated) == first
