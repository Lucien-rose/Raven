from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raven.contracts import HardRule, Item, RuleCheck, RuleOperator, RuleResult


def _resolve(item: Item, field: str) -> Any:
    if field == "age_hours":
        if item.created_at is None:
            return None
        created_at = item.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created_at).total_seconds() / 3600

    value: Any = item.model_dump(mode="python")
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(actual: Any, rule: HardRule) -> bool:
    expected = rule.value
    operator = rule.operator

    if operator == RuleOperator.EXISTS:
        return (actual is not None) is bool(expected)
    if operator == RuleOperator.EQUALS:
        return actual == expected
    if operator == RuleOperator.NOT_EQUALS:
        return actual != expected
    if operator == RuleOperator.IN:
        return actual in expected if expected is not None else False
    if operator == RuleOperator.NOT_IN:
        return actual not in expected if expected is not None else True
    if operator == RuleOperator.CONTAINS:
        return expected in actual if actual is not None else False
    if operator == RuleOperator.NOT_CONTAINS:
        return expected not in actual if actual is not None else True
    if actual is None:
        return False
    if operator == RuleOperator.LT:
        return actual < expected
    if operator == RuleOperator.LTE:
        return actual <= expected
    if operator == RuleOperator.GT:
        return actual > expected
    if operator == RuleOperator.GTE:
        return actual >= expected
    raise ValueError(f"Unsupported rule operator: {operator}")


def evaluate_rules(item: Item, rules: list[HardRule]) -> RuleResult:
    checks = [
        RuleCheck(rule_id=rule.id, passed=_matches(actual := _resolve(item, rule.field), rule), actual=actual)
        for rule in rules
    ]
    return RuleResult(passed=all(check.passed for check in checks), checks=checks)
