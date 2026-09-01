"""Live Trend & Inspiration Discovery — domain models.

Discovery is OPTIONAL. With mode OFF nothing here is constructed and the engine behaves
exactly as it does without the module.

Imports only `app.core` and `app.domain`, keeping it at the bottom of the stack.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from app.domain.common import Frozen, Score
from app.domain.reference import ReferenceDimension, ReferenceType


# ─────────────────────────── vocabulary ───────────────────────────

class TrendDomain(StrEnum):
    """Movies and TV are two entries among twenty-six, never the default."""
    ENTERTAINMENT = "ENTERTAINMENT"
    MOVIES = "MOVIES"
    TV_SERIES = "TV_SERIES"
    STREAMING = "STREAMING"
    GAMES = "GAMES"
    FASHION = "FASHION"
    ARCHITECTURE = "ARCHITECTURE"
    INTERIOR_DESIGN = "INTERIOR_DESIGN"
    ART = "ART"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    MUSIC = "MUSIC"
    STAGE_DESIGN = "STAGE_DESIGN"
    EVENT_DESIGN = "EVENT_DESIGN"
    WEDDING_DESIGN = "WEDDING_DESIGN"
    CULTURE = "CULTURE"
    TECHNOLOGY = "TECHNOLOGY"
    PRODUCT_DESIGN = "PRODUCT_DESIGN"
    AUTOMOTIVE = "AUTOMOTIVE"
    NATURE = "NATURE"
    TRAVEL = "TRAVEL"
    HOSPITALITY = "HOSPITALITY"
    SOCIAL_VISUAL_CULTURE = "SOCIAL_VISUAL_CULTURE"
    BRAND_DESIGN = "BRAND_DESIGN"
    EXHIBITIONS = "EXHIBITIONS"
    FESTIVALS = "FESTIVALS"
    OTHER = "OTHER"


class TrendMode(StrEnum):
    OFF = "OFF"
    CURRENT_INSPIRATION = "CURRENT_INSPIRATION"
    TRENDING_NOW = "TRENDING_NOW"
    DESIGN_TRENDS = "DESIGN_TRENDS"
    CULTURAL_MOMENT = "CULTURAL_MOMENT"
    SURPRISE_ME = "SURPRISE_ME"
    CUSTOM = "CUSTOM"


class TrendFreshness(StrEnum):
    UNDATED = "UNDATED"          # no evidence carries a verifiable date — assert nothing
    EMERGING = "EMERGING"
    CURRENT = "CURRENT"
    ESTABLISHED = "ESTABLISHED"
    DECLINING = "DECLINING"
    EVERGREEN = "EVERGREEN"


class SourceTier(StrEnum):
    OFFICIAL = "OFFICIAL"
    MAJOR_PUBLICATION = "MAJOR_PUBLICATION"
    TRADE_PUBLICATION = "TRADE_PUBLICATION"
    AGGREGATOR = "AGGREGATOR"
    COMMUNITY = "COMMUNITY"
    SOCIAL = "SOCIAL"


TIER_SCORE: dict[SourceTier, float] = {
    SourceTier.OFFICIAL: 1.00,
    SourceTier.MAJOR_PUBLICATION: 0.85,
    SourceTier.TRADE_PUBLICATION: 0.80,
    SourceTier.AGGREGATOR: 0.55,
    SourceTier.COMMUNITY: 0.40,
    SourceTier.SOCIAL: 0.25,
}


# ─────────────────────────── models ───────────────────────────

class EvidenceType(StrEnum):
    SEARCH_RESULT = "SEARCH_RESULT"
    PAGE = "PAGE"
    FIXTURE = "FIXTURE"


class TrendEvidence(Frozen):
    """Every trend claim carries one of these. Nothing is asserted without a source.

    Dates are never fabricated: an unresolvable date fragment yields `published=None`
    rather than a guess.
    """
    source: str
    source_tier: SourceTier = SourceTier.AGGREGATOR
    url: str | None = None
    published: date | None = None
    excerpt: str = ""
    is_mock: bool = False
    # ── added for live discovery; all optional so fixtures are unaffected ──
    title: str = ""
    publisher: str = ""
    canonical_url: str | None = None
    updated_at: date | None = None
    retrieved_at: datetime | None = None
    evidence_type: EvidenceType = EvidenceType.FIXTURE
    query: str = ""                       # the query that surfaced this
    syndicated_from: str | None = None    # set when collapsed into another item


class TrendSignal(Frozen):
    recency: Score = 0.5
    momentum: Score = 0.5
    relevance: Score = 0.5
    design_value: Score = 0.5
    source_quality: Score = 0.5
    novelty: Score = 0.5
    cross_domain_potential: Score = 0.5


class PrincipleHint(Frozen):
    """The transferable reading of a signal — what survives abstraction.

    Written by the fixture author or the analyser, never by the ranker: a hint is a
    design claim, and a ranker has no business making one.
    """
    dimension: ReferenceDimension
    statement: str
    abstraction: Score = 0.85
    salience: Score = 0.7
    suggests: list[str] = []          # ontology refs, validated downstream
    evidence_note: str = ""           # why a derived hint fired (live provider only)


class TrendCandidate(Frozen):
    candidate_id: str
    title: str
    domain: TrendDomain
    summary: str = ""
    evidence: list[TrendEvidence] = Field(min_length=1)
    signal: TrendSignal = TrendSignal()
    freshness: TrendFreshness = TrendFreshness.CURRENT
    principle_hints: list[PrincipleHint] = []
    surface_terms: list[str] = []     # brand/project names that must not reach a prompt
    literal_label: str = ""
    literal_facets: list[str] = []
    naive_rendering: str = ""
    suggested_reference_type: ReferenceType = ReferenceType.OTHER
    score: float = 0.0
    why_selected: str = ""
    is_mock: bool = False
    # ── live-discovery provenance; optional, so mock fixtures are unchanged ──
    entity: str = ""                          # resolved identity, never a raw headline
    independent_sources: int | None = None    # after syndication collapse
    low_confidence: bool = False              # < 2 independent sources, or undated
    freshness_confidence: float | None = None
    freshness_evidence: list[str] = []
    design_value_estimate: float | None = None
    design_value_confidence: float | None = None
    design_value_uncertain: bool = False
    design_value_reason: str = ""
    rejected_reason: str = ""                 # why it never reached selection
    queries: list[str] = []
    notes: str = ""                           # syndication / sanitisation notes

    @model_validator(mode="after")
    def _mock_is_consistent(self) -> "TrendCandidate":
        if self.is_mock and not all(e.is_mock for e in self.evidence):
            raise ValueError("a mock candidate must carry only mock evidence")
        return self

    @property
    def corroboration(self) -> int:
        """Distinct sources. One viral post is not a trend."""
        return len({e.source.lower() for e in self.evidence})

    def newest(self) -> date | None:
        dates = [e.published for e in self.evidence if e.published]
        return max(dates) if dates else None

    def oldest(self) -> date | None:
        dates = [e.published for e in self.evidence if e.published]
        return min(dates) if dates else None


class TrendDomainPlan(Frozen):
    domain: TrendDomain
    priority: Score
    rationale: str
    queries: list[str] = []


class TrendDiscoveryRequest(Frozen):
    mode: TrendMode = TrendMode.OFF
    domains: list[TrendDomain] = []        # CUSTOM only; ignored otherwise
    max_candidates: int = Field(default=8, ge=1, le=16)
    max_selected: int = Field(default=3, ge=1, le=4)
    region: str | None = None              # never inferred (§15)
    event_date: date | None = None
    seed: int = 42

    @property
    def enabled(self) -> bool:
        return self.mode is not TrendMode.OFF


class TrendDiscoveryResult(Frozen):
    result_id: str
    mode: TrendMode
    plan: list[TrendDomainPlan] = []
    queries: list[str] = []
    candidates: list[TrendCandidate] = []
    selected_ids: list[str] = []
    provider: str = "mock"
    is_mock: bool = True
    cached_queries: list[str] = []
    generated_at: datetime | None = None
    region: str | None = None
    notes: str = ""
    # ── live-discovery health; optional ──
    unavailable: bool = False                 # TREND_DISCOVERY_UNAVAILABLE
    failed_domains: list[str] = []
    search_calls: int = 0
    raw_results: int = 0
    rejected: list[str] = []

    def selected(self) -> list[TrendCandidate]:
        by_id = {c.candidate_id: c for c in self.candidates}
        return [by_id[i] for i in self.selected_ids if i in by_id]

    def domain_spread(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.selected():
            out[c.domain.value] = out.get(c.domain.value, 0) + 1
        return out
