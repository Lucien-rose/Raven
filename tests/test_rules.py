from datetime import UTC, datetime, timedelta

from raven.contracts import HardRule, Item, RuleOperator
from raven.rules import evaluate_rules


def test_rules_filter_structured_fields_and_age() -> None:
    item = Item(
        source_type="github",
        source_id="owner/repo",
        external_id="issue:1",
        url="https://github.com/owner/repo/issues/1",
        title="State bug",
        created_at=datetime.now(UTC) - timedelta(hours=2),
        metadata={"state": "open", "assignee_count": 0, "labels": ["bug"]},
    )
    rules = [
        HardRule(id="open", field="metadata.state", operator=RuleOperator.EQUALS, value="open"),
        HardRule(id="fresh", field="age_hours", operator=RuleOperator.LT, value=24),
        HardRule(
            id="free",
            field="metadata.assignee_count",
            operator=RuleOperator.EQUALS,
            value=0,
        ),
        HardRule(
            id="bug",
            field="metadata.labels",
            operator=RuleOperator.CONTAINS,
            value="bug",
        ),
    ]

    result = evaluate_rules(item, rules)

    assert result.passed
    assert all(check.passed for check in result.checks)
