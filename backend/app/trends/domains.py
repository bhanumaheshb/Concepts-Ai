"""TRD-00 — domain selection.

The engine decides WHERE to look from the brief, before it looks. There is no global
default domain set and movies are never privileged.
"""
from __future__ import annotations

from app.core.seeded import SeededRandom
from app.domain.brief import DesignProgram
from app.domain.common import Typology
from app.domain.trend import TrendDomain as D
from app.domain.trend import TrendDomainPlan, TrendMode

MAX_DOMAINS = 5
SURPRISE_FAR_DOMAINS = 2

# 1 — typology prior. Each typology looks in a different part of the world.
TYPOLOGY_PRIORS: dict[Typology, dict[D, float]] = {
    Typology.WEDDING_MANDAP: {
        D.WEDDING_DESIGN: 0.95, D.EVENT_DESIGN: 0.92, D.STAGE_DESIGN: 0.85,
        D.ARCHITECTURE: 0.80, D.FASHION: 0.78, D.ENTERTAINMENT: 0.62,
        D.HOSPITALITY: 0.58, D.ART: 0.55, D.MUSIC: 0.50, D.CULTURE: 0.55,
        D.SOCIAL_VISUAL_CULTURE: 0.48, D.AUTOMOTIVE: 0.10, D.GAMES: 0.15,
    },
    Typology.EVENT_STAGE: {
        D.STAGE_DESIGN: 0.95, D.EVENT_DESIGN: 0.88, D.ENTERTAINMENT: 0.80,
        D.MUSIC: 0.75, D.TECHNOLOGY: 0.72, D.ART: 0.62, D.ARCHITECTURE: 0.60,
        D.FASHION: 0.55, D.FESTIVALS: 0.70, D.AUTOMOTIVE: 0.12,
    },
    Typology.RESTAURANT: {
        D.INTERIOR_DESIGN: 0.95, D.HOSPITALITY: 0.92, D.ARCHITECTURE: 0.85,
        D.PRODUCT_DESIGN: 0.65, D.TECHNOLOGY: 0.62, D.ART: 0.58,
        D.FASHION: 0.52, D.BRAND_DESIGN: 0.55, D.TRAVEL: 0.45, D.GAMES: 0.12,
    },
    Typology.INTERIOR: {
        D.INTERIOR_DESIGN: 0.95, D.ARCHITECTURE: 0.88, D.PRODUCT_DESIGN: 0.72,
        D.ART: 0.65, D.FASHION: 0.55, D.TECHNOLOGY: 0.50, D.NATURE: 0.45,
    },
    Typology.PAVILION: {
        D.ARCHITECTURE: 0.95, D.EXHIBITIONS: 0.82, D.ART: 0.72,
        D.TECHNOLOGY: 0.68, D.NATURE: 0.62, D.FESTIVALS: 0.60,
        D.PRODUCT_DESIGN: 0.50, D.STAGE_DESIGN: 0.48,
    },
    Typology.EXHIBITION: {
        D.EXHIBITIONS: 0.95, D.ART: 0.85, D.ARCHITECTURE: 0.75,
        D.BRAND_DESIGN: 0.70, D.TECHNOLOGY: 0.68, D.PHOTOGRAPHY: 0.55,
        D.INTERIOR_DESIGN: 0.52, D.PRODUCT_DESIGN: 0.50,
    },
    Typology.GENERIC_SPATIAL: {
        D.ARCHITECTURE: 0.80, D.INTERIOR_DESIGN: 0.70, D.ART: 0.62,
        D.EVENT_DESIGN: 0.60, D.TECHNOLOGY: 0.55, D.FASHION: 0.50,
        D.CULTURE: 0.50, D.NATURE: 0.42,
    },
}

# 2 — the brief's own words move domains up or down
KEYWORD_SIGNALS: list[tuple[tuple[str, ...], dict[D, float]]] = [
    (("luxury", "premium", "opulent", "high-end"),
     {D.FASHION: +0.12, D.HOSPITALITY: +0.10, D.BRAND_DESIGN: +0.08}),
    (("futuristic", "future", "sci-fi", "tech", "digital", "interactive"),
     {D.TECHNOLOGY: +0.25, D.PRODUCT_DESIGN: +0.12, D.AUTOMOTIVE: +0.15, D.GAMES: +0.12}),
    (("retail", "store", "flagship", "shop"),
     {D.BRAND_DESIGN: +0.38, D.FASHION: +0.32, D.PRODUCT_DESIGN: +0.22,
      D.INTERIOR_DESIGN: +0.20}),
    (("natural", "garden", "botanical", "organic", "landscape", "outdoor"),
     {D.NATURE: +0.28, D.ARCHITECTURE: +0.06}),
    (("performance", "concert", "show", "theatrical", "stage"),
     {D.STAGE_DESIGN: +0.22, D.MUSIC: +0.18, D.ENTERTAINMENT: +0.15}),
    (("cinematic", "film", "movie", "series", "screen"),
     {D.MOVIES: +0.25, D.TV_SERIES: +0.20, D.ENTERTAINMENT: +0.18, D.PHOTOGRAPHY: +0.10}),
    (("crazy", "experimental", "radical", "unexpected", "bold", "wild"),
     {D.ART: +0.18, D.EXHIBITIONS: +0.12, D.NATURE: +0.10, D.GAMES: +0.10}),
    (("museum", "gallery", "biennale", "installation"),
     {D.EXHIBITIONS: +0.25, D.ART: +0.20}),
    (("hotel", "lobby", "resort", "spa"),
     {D.HOSPITALITY: +0.25, D.TRAVEL: +0.18, D.INTERIOR_DESIGN: +0.12}),
    # a Sangeeth is a wedding event even when the typology classifier reads it as
    # generic; the keyword must be strong enough to surface the domain on its own
    (("wedding", "sangeeth", "sangeet", "mehendi", "reception", "baraat", "haldi"),
     {D.WEDDING_DESIGN: +0.38, D.EVENT_DESIGN: +0.30, D.FASHION: +0.15,
      D.MUSIC: +0.12, D.STAGE_DESIGN: +0.20}),
    (("festival", "carnival", "parade"),
     {D.FESTIVALS: +0.28, D.EVENT_DESIGN: +0.12}),
    (("minimal", "restrained", "quiet", "calm"),
     {D.INTERIOR_DESIGN: +0.10, D.ARCHITECTURE: +0.08, D.SOCIAL_VISUAL_CULTURE: -0.15}),
]

# 3 — mode adjustment
DESIGN_CLUSTER = (D.ARCHITECTURE, D.INTERIOR_DESIGN, D.PRODUCT_DESIGN, D.FASHION,
                  D.ART, D.STAGE_DESIGN, D.EVENT_DESIGN, D.BRAND_DESIGN)
CULTURE_CLUSTER = (D.ENTERTAINMENT, D.MOVIES, D.TV_SERIES, D.STREAMING, D.MUSIC,
                   D.CULTURE, D.SOCIAL_VISUAL_CULTURE, D.GAMES, D.FESTIVALS)

RATIONALE = {
    "prior": "core domain for this typology",
    "keyword": "raised by the brief's own language",
    "mode": "raised by the selected trend mode",
    "far": "deliberately distant from the brief — the discovery this mode exists for",
    "custom": "chosen by the designer",
}


def select_domains(program: DesignProgram, brief_text: str, mode: TrendMode,
                   custom: list[D] | None = None, seed: int = 42) -> list[TrendDomainPlan]:
    if mode is TrendMode.CUSTOM and custom:
        return [TrendDomainPlan(domain=d, priority=0.9, rationale=RATIONALE["custom"])
                for d in custom[:MAX_DOMAINS]]

    scores: dict[D, float] = dict(
        TYPOLOGY_PRIORS.get(program.typology, TYPOLOGY_PRIORS[Typology.GENERIC_SPATIAL]))
    why: dict[D, str] = {d: RATIONALE["prior"] for d in scores}

    low = brief_text.lower()
    for words, deltas in KEYWORD_SIGNALS:
        if not any(w in low for w in words):
            continue
        for d, delta in deltas.items():
            scores[d] = min(1.0, max(0.0, scores.get(d, 0.40) + delta))
            if delta > 0:
                why[d] = RATIONALE["keyword"]

    if mode is TrendMode.DESIGN_TRENDS:
        for d in DESIGN_CLUSTER:
            scores[d] = min(1.0, scores.get(d, 0.40) + 0.20)
            why.setdefault(d, RATIONALE["mode"])
    elif mode is TrendMode.CULTURAL_MOMENT:
        for d in CULTURE_CLUSTER:
            scores[d] = min(1.0, scores.get(d, 0.35) + 0.22)
            why.setdefault(d, RATIONALE["mode"])
    elif mode is TrendMode.TRENDING_NOW:
        for d in (*CULTURE_CLUSTER, D.FASHION):
            scores[d] = min(1.0, scores.get(d, 0.35) + 0.10)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].value))
    chosen = [d for d, _ in ranked[:MAX_DOMAINS]]

    if mode is TrendMode.SURPRISE_ME:
        # far-domain injection: the same inverted-retrieval trick the architecture doc
        # argues for, applied to domains. Two of five slots go to the LEAST likely
        # domains that are still plausible, which is where genuine discovery lives.
        rng = SeededRandom(seed, "surprise", program.program_id)
        far_pool = [d for d, s in ranked if 0.10 <= s <= 0.55] or [d for d, _ in ranked[-6:]]
        far = rng.sample_without_replacement(far_pool, [1.0] * len(far_pool),
                                             SURPRISE_FAR_DOMAINS)
        chosen = chosen[: MAX_DOMAINS - len(far)] + far
        for d in far:
            why[d] = RATIONALE["far"]

    return [TrendDomainPlan(domain=d, priority=round(min(1.0, scores.get(d, 0.4)), 3),
                            rationale=why.get(d, RATIONALE["prior"]))
            for d in chosen]
