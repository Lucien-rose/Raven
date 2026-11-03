from __future__ import annotations

from raven.contracts import CandidateContext, Item, WatchSpec
from raven.diff import diff_items
from raven.judges.base import SemanticJudge
from raven.rules import evaluate_rules


class WatchRuntime:
    def __init__(self, judge: SemanticJudge | None = None) -> None:
        self._judge = judge

    async def evaluate(
        self,
        watch: WatchSpec,
        item: Item,
        previous: Item | None = None,
    ) -> CandidateContext | None:
        if watch.id is None:
            raise ValueError("WatchSpec must have an id before runtime evaluation")
        if watch.judge is not None and self._judge is None:
            raise RuntimeError(
                f"Watch requests judge {watch.judge.adapter!r}, but no judge adapter is configured"
            )

        diff = diff_items(previous, item)
        if previous is not None and not diff:
            return None

        rule_result = evaluate_rules(item, watch.hard_rules)
        if not rule_result.passed:
            return None

        verdict = None
        if self._judge is not None and watch.judge is not None:
            verdict = await self._judge.evaluate(watch, item, rule_result, diff)
            if verdict.decision == "reject":
                return None

        return CandidateContext(
            watch_id=watch.id,
            watch_spec_version=watch.version,
            item=item,
            diff=diff,
            rule_result=rule_result,
            semantic_verdict=verdict,
        )
