from __future__ import annotations

from typing import Any, Protocol

from raven.contracts import Item, RuleResult, SemanticVerdict, WatchSpec


class SemanticJudge(Protocol):
    async def evaluate(
        self,
        watch: WatchSpec,
        item: Item,
        rule_result: RuleResult,
        diff: dict[str, Any],
        config: dict[str, Any],
    ) -> SemanticVerdict: ...
