from datetime import UTC, datetime

import pytest

from raven.contracts import CandidateContext, Item, RuleResult
from raven.delivery import EventDeliveryWorker
from raven.events import CandidateReadyEvent, OutboxEventDispatcher, load_event_status
from raven.storage import SQLiteStorage


class RecordingTransport:
    def __init__(self) -> None:
        self.triggers = []

    async def deliver(self, trigger) -> None:
        self.triggers.append(trigger)


class FailingTransport:
    async def deliver(self, trigger) -> None:
        raise RuntimeError("callback unavailable")


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


@pytest.mark.asyncio
async def test_delivery_sends_compact_trigger_and_marks_delivered(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    event = make_event()
    await OutboxEventDispatcher(storage).publish(event)

    transport = RecordingTransport()
    worker = EventDeliveryWorker(storage, transport)
    now = datetime(2026, 11, 4, tzinfo=UTC)

    await worker.tick(now)

    assert len(transport.triggers) == 1
    trigger = transport.triggers[0]
    assert trigger.event_id == event.id
    assert trigger.watch_id == event.watch_id
    assert not hasattr(trigger, "candidate")

    status = load_event_status(storage, event.id)
    assert status is not None
    assert status.delivery == "delivered"
    assert status.attempts == 1
    assert status.delivered_at == now


@pytest.mark.asyncio
async def test_delivery_failure_schedules_retry(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()
    event = make_event()
    await OutboxEventDispatcher(storage).publish(event)

    worker = EventDeliveryWorker(storage, FailingTransport())
    now = datetime(2026, 11, 4, tzinfo=UTC)

    await worker.tick(now)

    status = load_event_status(storage, event.id)
    assert status is not None
    assert status.delivery == "retry"
    assert status.attempts == 1
    assert status.last_error == "callback unavailable"
    assert status.next_attempt_at is not None

    await worker.tick(now)
    assert load_event_status(storage, event.id).attempts == 1
