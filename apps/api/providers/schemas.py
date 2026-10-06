"""Pydantic models for every router task's input and validated JSON output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Series = Literal[
    "Childhood Brands",
    "Tech Graveyard",
    "Fraud Files",
    "Everyday Genius",
    "Comebacks",
    "Recent Collapses",
]
Score = Field(ge=1, le=10)


# --- score_items -----------------------------------------------------------
class ItemToScore(BaseModel):
    id: str
    title: str
    snippet: str = ""
    source: str = ""
    url: str = ""


class ItemScore(BaseModel):
    id: str
    drama: int = Score
    twist: int = Score
    relatability: int = Score
    visual_potential: int = Score
    hook_number: int = Score
    freshness: int = Score
    hook: str
    series: Series
    format: Literal["Short", "Long"]
    company: str | None = Field(default=None, description="main company/brand, if any")


class ScoreBatch(BaseModel):
    scores: list[ItemScore]


# --- parse_mention ---------------------------------------------------------
class MentionParse(BaseModel):
    agent: Literal["scout", "outlier", "researcher"] | None
    params: dict[str, Any] = Field(default_factory=dict)
    confident: bool = Field(description="false if the request is ambiguous")


# --- extract_from_document -------------------------------------------------
class Extract(BaseModel):
    quote: str = Field(description="exact text copied from the document, short")
    note: str = ""


class DocExtraction(BaseModel):
    answer: str
    extracts: list[Extract] = Field(default_factory=list)
    found: bool


# --- analyze_outliers ------------------------------------------------------
class VideoForAnalysis(BaseModel):
    video_id: str
    channel: str
    title: str
    views: int
    outlier_score: float
    is_short: bool
    published_at: str | None = None


class OutlierAnalysis(BaseModel):
    video_id: str
    topic: str
    company_type: str
    hook_pattern: str
    why_it_worked: str
    wyrd_angle: str


class OutlierBatch(BaseModel):
    analyses: list[OutlierAnalysis]


# --- check_support ---------------------------------------------------------
class SupportItem(BaseModel):
    id: str
    claim: str
    excerpt: str


class SupportVerdict(BaseModel):
    id: str
    supported: bool = Field(description="true only if the excerpt supports EVERY factual part")
    unsupported_parts: list[str] = Field(
        default_factory=list, description="details in the claim the excerpt doesn't support"
    )
    trimmed_claim: str | None = Field(
        default=None,
        description="the claim with unsupported details removed, only if what remains is "
        "still a useful, fully supported statement; else null",
    )


class SupportBatch(BaseModel):
    verdicts: list[SupportVerdict]


# --- second_opinion --------------------------------------------------------
class ClaimFlag(BaseModel):
    claim: str
    issue: str
    severity: Literal["low", "medium", "high"]
    suggestion: str
    kind: Literal["unsupported", "interpretation", "superlative", "defamation", "weak_source"] = (
        Field(
            default="unsupported", description="interpretation = opinion/causation stated as fact"
        )
    )


class SecondOpinion(BaseModel):
    flags: list[ClaimFlag] = Field(default_factory=list)
    overall: str
