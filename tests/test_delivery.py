import json
from datetime import UTC, datetime

import pytest

from raven.contracts import CandidateContext, Item, RuleResult, WatchSpec
from raven.delivery import CallbackError, EventDeliveryWorker
from raven.events import CandidateReadyEvent, OutboxEventDispatcher, load_event_status
from raven.storage import SQLiteStorage


class RecordingSender:
    def __init__(self) -> None:
        self.deliveries = []

    async def send(self, event, subscription_id, url, secret) -> None:
        self.deliveries.append((event, subscription_id, url, secret))


class FailingSender:
    async def send(self, event, subscription_id, url, secret) -> None:
        raise CallbackError("callback unavailable")


def make_event() -> CandidateReadyEvent:
    return CandidateReadyEvent(
        watch_id="watch-1",
        candidate=CandidateContext(
            watch_id="watch-1",
            watch_spec_version="1",
            item=Item(
                source_type="github",
                source_id="owner/repo",
                external_id="issue:1",
                url="https://example.test/1",
                title="Bug",
            ),
            diff={"_new": True},
            rule_result=RuleResult(passed=True, checks=[]),
        ),
    )


def setup_delivery(storage: SQLiteStorage) -> CandidateReadyEvent:
    watch = WatchSpec(
        id="watch-1",
        name="Test",
        original_intent="Watch something",
        sources=[],
    )
    storage.save_watch(watch, owner="alice")
    storage.upsert_event_subscription(
        subscription_id="sub-1",
        owner="alice",
        event_name="candidate.ready",
        routing_key="watch-1",
        arguments_json=json.dumps({"watch_id": "watch-1"}),
        callback_url="https://example.com/events",
        secret="whsec_test",
        refresh_before=None,
    )
    return make_event()


@pytest.mark.asyncio
async def test_delivery_sends_once_per_subscription(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    event = setup_delivery(storage)
    await OutboxEventDispatcher(storage).publish(event)

    sender = RecordingSender()
    worker = EventDeliveryWorker(storage, sender)
    now = datetime(2026, 11, 4, tzinfo=UTC)

    await worker.tick(now)

    assert len(sender.deliveries) == 1
    _, subscription_id, _, _ = sender.deliveries[0]
    assert subscription_id == "sub-1"

    status = load_event_status(storage, event.id, owner="alice")
    assert status is not None
    assert status.deliveries[0].status == "delivered"
    assert status.deliveries[0].attempts == 1
    assert status.deliveries[0].delivered_at == now


@pytest.mark.asyncio
async def test_delivery_failure_schedules_retry(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    event = setup_delivery(storage)
    await OutboxEventDispatcher(storage).publish(event)

    worker = EventDeliveryWorker(storage, FailingSender())
    now = datetime(2026, 11, 4, tzinfo=UTC)

    await worker.tick(now)

    status = load_event_status(storage, event.id, owner="alice")
    assert status is not None
    delivery = status.deliveries[0]
    assert delivery.status == "retry"
    assert delivery.attempts == 1
    assert delivery.last_error == "callback unavailable"
    assert delivery.next_attempt_at is not None

    await worker.tick(now)
    assert load_event_status(storage, event.id, owner="alice").deliveries[0].attempts == 1
