import pytest

from raven.contracts import CandidateContext, IntervalSchedule, Item, RuleResult, WatchSpec
from raven.events import CandidateReadyEvent
from raven.scheduler import WatchScheduler
from raven.storage import SQLiteStorage


class FakeRunner:
    def __init__(self, candidate: CandidateContext) -> None:
        self.candidate = candidate
        self.calls = 0

    async def run_once(self, watch: WatchSpec) -> list[CandidateContext]:
        self.calls += 1
        return [self.candidate]


class FakeDispatcher:
    def __init__(self) -> None:
        self.events: list[CandidateReadyEvent] = []

    async def publish(self, event: CandidateReadyEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_scheduler_runs_due_watch_and_respects_interval(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "raven.db")
    storage.init()

    watch = WatchSpec(
        id="watch-1",
        name="Test",
        original_intent="Watch something",
        sources=[],
        schedule=IntervalSchedule(interval_seconds=10),
    )
    storage.save_watch(watch, owner="alice")

    candidate = CandidateContext(
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
    )
    runner = FakeRunner(candidate)
    dispatcher = FakeDispatcher()
    scheduler = WatchScheduler(storage, runner, dispatcher)

    await scheduler.tick(now=0)
    await scheduler.tick(now=5)
    await scheduler.tick(now=10)

    assert runner.calls == 2
    assert len(dispatcher.events) == 2
