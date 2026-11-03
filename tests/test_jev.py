import httpx
import pytest

from raven.contracts import (
    Item,
    RuleResult,
    SemanticCriterion,
    WatchSpec,
)
from raven.judges.jev import JevJudge


@pytest.mark.asyncio
async def test_jev_judge_maps_typed_choices_to_verdict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "model": "typesafe/jev-1.14",
            "answers": {
                "impact": {
                    "type": "choice",
                    "choice": "match",
                    "probabilities": {
                        "match": 0.91,
                        "no_match": 0.03,
                        "uncertain": 0.06,
                    },
                },
                "scope": {
                    "type": "choice",
                    "choice": "uncertain",
                    "probabilities": {
                        "match": 0.15,
                        "no_match": 0.10,
                        "uncertain": 0.75,
                    },
                },
            },
        }
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        judge = JevJudge(client, api_key="test")
        watch = WatchSpec(
            id="watch-1",
            name="Issue opportunities",
            original_intent="Find high-value issues",
            sources=[],
            semantic_criteria=[
                SemanticCriterion(id="impact", description="High user impact"),
                SemanticCriterion(id="scope", description="Narrow failure boundary"),
            ],
        )
        verdict = await judge.evaluate(
            watch=watch,
            item=Item(
                source_type="github",
                source_id="owner/repo",
                external_id="issue:1",
                url="https://example.test/1",
                title="Bug",
            ),
            rule_result=RuleResult(passed=True, checks=[]),
            diff={"_new": True},
            config={},
        )

    assert verdict.decision == "uncertain"
    assert verdict.signals[0].result == "match"
    assert verdict.signals[0].confidence == pytest.approx(0.91)
