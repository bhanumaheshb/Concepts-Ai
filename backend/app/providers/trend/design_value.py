"""Transparent design-value estimation.

The mock provider used an authored number. A live provider must not invent one. This
returns an estimate WITH a confidence and the features it rests on — and returns None
when the evidence cannot support a number at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.trend import TIER_SCORE, TrendDomain, TrendEvidence
from app.references.abstraction import relates      # the ladder's own RELATE predicate

MIN_CONFIDENCE = 0.40

# Vocabulary that indicates transferable SPATIAL content rather than commerce or hype.
SPATIAL_TERMS = {
    "light", "lighting", "shadow", "daylight", "material", "materials", "texture",
    "surface", "finish", "timber", "stone", "concrete", "steel", "glass", "terracotta",
    "geometry", "form", "volume", "plan", "section", "structure", "structural", "span",
    "facade", "threshold", "circulation", "flow", "route", "sightline", "scale",
    "proportion", "rhythm", "layered", "modular", "acoustic", "scent", "sensory",
    "spatial", "space", "spaces", "room", "interior", "silhouette", "shoulders",
    "sculptural", "biophilic", "living", "planting", "palette", "colour", "color",
    "tactile", "patina", "disassembly", "reuse", "circular", "seating", "wayfinding",
}
COMMERCE_TERMS = {
    "roi", "conversion", "sales", "revenue", "turnover", "brand recall", "marketing",
    "shoppers", "footfall", "loyalty", "personalisation", "personalization", "crm",
    "sku", "price", "discount", "campaign", "customers", "buy", "purchase",
}

# How design-bearing a domain is, before any evidence is read.
DOMAIN_PRIOR: dict[TrendDomain, float] = {
    TrendDomain.ARCHITECTURE: 0.90, TrendDomain.INTERIOR_DESIGN: 0.88,
    TrendDomain.EXHIBITIONS: 0.85, TrendDomain.STAGE_DESIGN: 0.85,
    TrendDomain.ART: 0.82, TrendDomain.PRODUCT_DESIGN: 0.78,
    TrendDomain.EVENT_DESIGN: 0.76, TrendDomain.FASHION: 0.72,
    TrendDomain.NATURE: 0.72, TrendDomain.PHOTOGRAPHY: 0.68,
    TrendDomain.TECHNOLOGY: 0.66, TrendDomain.HOSPITALITY: 0.66,
    TrendDomain.WEDDING_DESIGN: 0.64, TrendDomain.BRAND_DESIGN: 0.62,
    TrendDomain.ENTERTAINMENT: 0.58, TrendDomain.MOVIES: 0.55,
    TrendDomain.TV_SERIES: 0.52, TrendDomain.GAMES: 0.55,
    TrendDomain.MUSIC: 0.50, TrendDomain.FESTIVALS: 0.58,
    TrendDomain.CULTURE: 0.50, TrendDomain.TRAVEL: 0.48,
    TrendDomain.STREAMING: 0.45, TrendDomain.AUTOMOTIVE: 0.60,
    TrendDomain.SOCIAL_VISUAL_CULTURE: 0.40, TrendDomain.OTHER: 0.50,
}

W = {"spatial_lexicon": 0.34, "transferability": 0.28, "domain_prior": 0.22,
     "source_signal": 0.16}


@dataclass(frozen=True)
class DesignValueEstimate:
    estimate: float | None          # None when the evidence cannot support a number
    confidence: float
    features: dict[str, float]
    reason: str

    @property
    def uncertain(self) -> bool:
        return self.estimate is None or self.confidence < MIN_CONFIDENCE


def _text_of(evidence: list[TrendEvidence]) -> str:
    return " ".join(f"{e.title} {e.excerpt}" for e in evidence).lower()


def estimate_design_value(evidence: list[TrendEvidence], domain: TrendDomain
                          ) -> DesignValueEstimate:
    if not evidence:
        return DesignValueEstimate(None, 0.0, {}, "no evidence")

    text = _text_of(evidence)
    words = [w.strip(".,;:!?()\"'") for w in text.split()]
    total = max(1, len(words))

    spatial_hits = sum(1 for w in words if w in SPATIAL_TERMS)
    commerce_hits = sum(1 for w in words if w in COMMERCE_TERMS)
    # density normalised against a realistic ceiling, then penalised by commerce framing
    spatial = min(1.0, (spatial_hits / total) / 0.09)
    spatial = max(0.0, spatial - min(0.35, commerce_hits / total / 0.06 * 0.35))

    # does at least one excerpt describe a RELATION rather than list nouns?
    relational = [e for e in evidence if e.excerpt and relates(e.excerpt)]
    transferability = min(1.0, len(relational) / max(1, min(3, len(evidence))))

    prior = DOMAIN_PRIOR.get(domain, 0.5)
    source_signal = max(TIER_SCORE[e.source_tier] for e in evidence)

    features = {"spatial_lexicon": round(spatial, 4),
                "transferability": round(transferability, 4),
                "domain_prior": round(prior, 4),
                "source_signal": round(source_signal, 4)}
    estimate = sum(W[k] * v for k, v in features.items())

    # confidence is about EVIDENCE SUFFICIENCY, not about the estimate's value
    excerpt_chars = sum(len(e.excerpt) for e in evidence)
    conf = (0.40 * min(1.0, len(evidence) / 3.0)
            + 0.35 * min(1.0, excerpt_chars / 400.0)
            + 0.25 * source_signal)
    if not relational:
        conf *= 0.7           # nothing transferable was actually observed
    conf = round(min(1.0, conf), 4)

    if conf < MIN_CONFIDENCE:
        return DesignValueEstimate(
            None, conf, features,
            f"DESIGN_VALUE_UNCERTAIN: {len(evidence)} source(s), "
            f"{excerpt_chars} chars of excerpt, "
            f"{'no' if not relational else len(relational)} relational statement(s)")

    return DesignValueEstimate(
        round(min(1.0, estimate), 4), conf, features,
        f"estimated from {len(evidence)} source(s); "
        f"spatial-term density {spatial:.2f}, "
        f"{len(relational)} relational statement(s), domain prior {prior:.2f}")
