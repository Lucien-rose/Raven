from __future__ import annotations

from raven.contracts import CandidateContext, Item, WatchMode, WatchSpec
from raven.diff import diff_items
from raven.judges.base import SemanticJudge
from raven.rules import evaluate_rules


class WatchRuntime:
    def __init__(self, judges: dict[str, SemanticJudge] | None = None) -> None:
        self._judges = judges or {}

    async def evaluate(
        self,
        watch: WatchSpec,
        item: Item,
        previous: Item | None = None,
    ) -> CandidateContext | None:
        if watch.id is None:
            raise ValueError("WatchSpec must have an id before runtime evaluation")

        diff = diff_items(previous, item)
        if previous is not None and not diff:
            return None

        rule_result = evaluate_rules(item, watch.hard_rules)
        if not rule_result.passed:
            return None

        verdict = None
        if watch.judge is not None:
            judge = self._judges.get(watch.judge.adapter)
            if judge is None:
                raise RuntimeError(
                    f"Judge adapter {watch.judge.adapter!r} is not configured"
                )

            verdict = await judge.evaluate(
                watch,
                item,
                rule_result,
                diff,
                watch.judge.config,
            )
            if verdict.decision == "reject":
                return None
            if verdict.decision == "uncertain" and watch.mode == WatchMode.STRICT:
                return None

        return CandidateContext(
            watch_id=watch.id,
            watch_spec_version=watch.version,
            item=item,
            diff=diff,
            rule_result=rule_result,
            semantic_verdict=verdict,
        )
