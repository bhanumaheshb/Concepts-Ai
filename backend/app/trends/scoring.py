"""TRD-03/04 — freshness classification and the trend score.

A ranking heuristic, and stated as one. Its job is only: which discovered signals are
worth handing to the Creative Engine?
"""
from __future__ import annotations

from datetime import date

from app.domain.trend import (
    TIER_SCORE, SourceTier, TrendCandidate, TrendFreshness, TrendMode, TrendSignal,
)

BASE_WEIGHTS = {
    "relevance": 0.26, "design_value": 0.26, "source_quality": 0.16,
    "recency": 0.12, "novelty": 0.10, "cross_domain_potential": 0.06, "momentum": 0.04,
}
# §9 — popularity is not design value. A signal with little transferable spatial
# content is capped no matter how much momentum it has.
DESIGN_VALUE_FLOOR = 0.35
POPULARITY_CAP = 0.45

MODE_BOOST: dict[TrendMode, dict[str, float]] = {
    TrendMode.TRENDING_NOW: {"recency": 2.0, "momentum": 2.0},
    TrendMode.DESIGN_TRENDS: {"design_value": 2.0, "source_quality": 1.3},
    TrendMode.CULTURAL_MOMENT: {"recency": 1.5, "cross_domain_potential": 1.4},
    TrendMode.SURPRISE_ME: {"novelty": 2.0, "cross_domain_potential": 2.0},
    TrendMode.CURRENT_INSPIRATION: {},
    TrendMode.CUSTOM: {},
    TrendMode.OFF: {},
}

HOST_TIERS: list[tuple[tuple[str, ...], SourceTier]] = [
    (("gov", "edu", "official", "museum", "biennale"), SourceTier.OFFICIAL),
    (("dezeen", "archdaily", "designboom", "wallpaper", "domus", "architectural",
      "vogue", "businessoffashion", "variety", "hollywoodreporter"), SourceTier.MAJOR_PUBLICATION),
    (("frameweb", "eventmb", "bizbash", "interiordesign", "wgsn", "trade", "report"),
     SourceTier.TRADE_PUBLICATION),
    (("medium", "substack", "blog", "aggregator"), SourceTier.AGGREGATOR),
    (("reddit", "forum", "community"), SourceTier.COMMUNITY),
    (("instagram", "tiktok", "pinterest", "twitter", "x.com"), SourceTier.SOCIAL),
]


def tier_for(source: str) -> SourceTier:
    low = source.lower()
    for keys, tier in HOST_TIERS:
        if any(k in low for k in keys):
            return tier
    return SourceTier.AGGREGATOR


def source_quality(candidate: TrendCandidate) -> float:
    """Best tier present, lifted slightly by independent corroboration."""
    if not candidate.evidence:
        return 0.0
    best = max(TIER_SCORE[e.source_tier] for e in candidate.evidence)
    bonus = min(0.10, 0.05 * max(0, candidate.corroboration - 1))
    return min(1.0, best + bonus)


def classify_freshness(candidate: TrendCandidate, today: date) -> TrendFreshness:
    """Derived from the evidence, never asserted. A 2019 article cannot be 'trending
    now' because its newest evidence date forbids it."""
    newest, oldest = candidate.newest(), candidate.oldest()
    if newest is None:
        # Returning CURRENT here asserted currency from nothing — the precise failure
        # the brief warns about. Undated evidence supports no freshness claim at all.
        return TrendFreshness.UNDATED
    age = (today - newest).days
    span = (newest - oldest).days if oldest else 0
    n = candidate.corroboration

    if age > 540:
        return TrendFreshness.DECLINING
    if span > 1095 and n >= 3:
        return TrendFreshness.EVERGREEN
    if age <= 90 and n <= 2 and candidate.signal.momentum >= 0.6:
        return TrendFreshness.EMERGING
    if span > 365 and n >= 3:
        return TrendFreshness.ESTABLISHED
    if age <= 270 and n >= 2:
        return TrendFreshness.CURRENT
    return TrendFreshness.CURRENT


def recency_from(candidate: TrendCandidate, today: date) -> float:
    newest = candidate.newest()
    if newest is None:
        return 0.5
    age = max(0, (today - newest).days)
    return round(max(0.0, min(1.0, 1.0 - age / 730.0)), 4)


def _momentum_adjusted(signal: TrendSignal, candidate: TrendCandidate, sq: float) -> float:
    """One viral post is not a trend: momentum only counts once two independent
    sources corroborate, and it is scaled by how good those sources are."""
    return signal.momentum * min(1.0, candidate.corroboration / 2.0) * sq


def score_candidate(candidate: TrendCandidate, mode: TrendMode, today: date) -> float:
    sq = source_quality(candidate)
    s = candidate.signal
    values = {
        "relevance": s.relevance,
        "design_value": s.design_value,
        "source_quality": sq,
        "recency": recency_from(candidate, today),
        "novelty": s.novelty,
        "cross_domain_potential": s.cross_domain_potential,
        "momentum": _momentum_adjusted(s, candidate, sq),
    }
    boosts = MODE_BOOST.get(mode, {})
    weights = {k: BASE_WEIGHTS[k] * boosts.get(k, 1.0) for k in BASE_WEIGHTS}
    total_w = sum(weights.values())
    base = sum(weights[k] * values[k] for k in values) / total_w

    if s.design_value < DESIGN_VALUE_FLOOR:
        base = min(base, POPULARITY_CAP)      # §9, explicitly
    return round(max(0.0, min(1.0, base)), 4)


def explain(candidate: TrendCandidate, mode: TrendMode, today: date,
            domain_rationale: str) -> str:
    """§16 — why this was selected, in words a designer can disagree with."""
    fresh = classify_freshness(candidate, today)
    n = candidate.corroboration
    best = max((e.source_tier for e in candidate.evidence),
               key=lambda t: TIER_SCORE[t]) if candidate.evidence else SourceTier.AGGREGATOR
    return (
        f"{fresh.value.lower().capitalize()} in {candidate.domain.value.replace('_', ' ').lower()} "
        f"({domain_rationale}), corroborated by {n} "
        f"{'source' if n == 1 else 'independent sources'} at {best.value.replace('_', ' ').lower()} "
        f"level. Selected for transferable spatial principles "
        f"(design value {candidate.signal.design_value:.2f}), not for popularity."
    )
