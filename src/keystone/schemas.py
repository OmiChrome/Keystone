"""Shared data contract for every Keystone specialist ("keystone/1.0").

Every agent returns an ``AgentResult`` envelope. Evidence, confidence and human-review flags have
the same shape across the suite, so one specialist's output can be fed straight into another and
Amber (the orchestrator) can reason about any of them uniformly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "keystone/1.0"


class Evidence(BaseModel):
    """A pointer to exactly where a fact came from."""

    doc_id: str
    doc_name: str
    page: int | None = Field(None, description="1-based page number for documents")
    locator: str | None = Field(None, description="Row / paragraph / cell locator, e.g. 'row 4' or '2.1.C'")
    quote: str = Field("", description="Verbatim text from the source")
    verified: bool = Field(False, description="True if the quote was found in the source text by string matching")
    match_score: float = Field(0.0, description="0-100 fuzzy match score of the quote against the source")
    url: str | None = None


class Confidence(BaseModel):
    score: float = Field(..., ge=0, le=1)
    level: Literal["high", "medium", "low"]
    factors: dict[str, float] = Field(default_factory=dict, description="Signals that produced the score")
    rationale: str = ""

    @classmethod
    def from_score(cls, score: float, factors: dict[str, float] | None = None, rationale: str = "") -> "Confidence":
        score = max(0.0, min(1.0, round(score, 3)))
        level = "high" if score >= 0.8 else "medium" if score >= 0.6 else "low"
        return cls(score=score, level=level, factors=factors or {}, rationale=rationale)


class HumanReview(BaseModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    models: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    llm_latency_s: float = 0.0
    wall_time_s: float = 0.0
    trace: list[dict[str, Any]] = Field(default_factory=list, description="Every model call made in this run (purpose, model, latency, cache hit)")


class AgentResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    agent: str
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    status: Literal["complete", "needs_human_review", "error"] = "complete"
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    confidence: Confidence
    human_review: HumanReview = Field(default_factory=HumanReview)
    usage: Usage = Field(default_factory=Usage)
    inputs: dict[str, Any] = Field(default_factory=dict, description="Echo of the inputs (ids, not payloads)")


# ------------------------------------------------------------------ shared domain objects (suite-wide)


class EquipmentItem(BaseModel):
    """An item of equipment as it moves through bid -> submittal -> PO -> delivery."""

    item_id: str
    description: str
    category: str | None = None
    vendor: str | None = None
    quoted_lead_weeks: float | None = None
    order_date: str | None = None
    promised_date: str | None = None
    need_by_date: str | None = None
    po_number: str | None = None
    shipment_mode: str | None = Field(None, description="Ocean | Truck | Air | Air Charter")
