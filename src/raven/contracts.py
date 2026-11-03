from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class WatchMode(StrEnum):
    BROAD = "broad"
    BALANCED = "balanced"
    STRICT = "strict"


class RuleOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    EXISTS = "exists"


class HardRule(BaseModel):
    id: str
    field: str
    operator: RuleOperator
    value: Any = None


class SemanticCriterion(BaseModel):
    id: str
    description: str


class RubricDimension(BaseModel):
    id: str
    description: str
    weight: float


class SourceBinding(BaseModel):
    type: str
    target: str
    config: dict[str, Any] = Field(default_factory=dict)


class JudgeConfig(BaseModel):
    adapter: str
    config: dict[str, Any] = Field(default_factory=dict)


class WatchSpec(BaseModel):
    version: Literal["1"] = "1"
    id: str | None = None
    name: str
    original_intent: str
    sources: list[SourceBinding]
    hard_rules: list[HardRule] = Field(default_factory=list)
    semantic_criteria: list[SemanticCriterion] = Field(default_factory=list)
    scoring_rubric: list[RubricDimension] = Field(default_factory=list)
    mode: WatchMode = WatchMode.BALANCED
    judge: JudgeConfig | None = None
    explicit_constraints: list[str] = Field(default_factory=list)
    inferred_preferences: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class Item(BaseModel):
    version: Literal["1"] = "1"
    source_type: str
    source_id: str
    external_id: str
    url: str
    title: str
    content: str = ""
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuleCheck(BaseModel):
    rule_id: str
    passed: bool
    actual: Any = None


class RuleResult(BaseModel):
    passed: bool
    checks: list[RuleCheck]


class SemanticSignal(BaseModel):
    criterion_id: str
    result: Literal["match", "no_match", "uncertain"]
    confidence: float
    reason: str = ""


class SemanticVerdict(BaseModel):
    version: Literal["1"] = "1"
    decision: Literal["pass", "reject", "uncertain"]
    confidence: float
    signals: list[SemanticSignal] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class CandidateContext(BaseModel):
    version: Literal["1"] = "1"
    watch_id: str
    watch_spec_version: str
    item: Item
    diff: dict[str, Any]
    rule_result: RuleResult
    semantic_verdict: SemanticVerdict | None = None
