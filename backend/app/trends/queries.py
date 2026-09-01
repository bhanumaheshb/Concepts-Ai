"""TRD-01 — query generation.

Queries are built FROM THE BRIEF. "trending design 2026" for every user is exactly the
failure this module exists to avoid.
"""
from __future__ import annotations

import re
from datetime import date

from app.domain.brief import DesignProgram
from app.domain.trend import TrendDomain as D
from app.domain.trend import TrendDomainPlan, TrendMode

MAX_QUERIES_PER_DOMAIN = 3

DOMAIN_PHRASE: dict[D, str] = {
    D.ARCHITECTURE: "architecture", D.INTERIOR_DESIGN: "interior design",
    D.EVENT_DESIGN: "experiential event design", D.WEDDING_DESIGN: "wedding design",
    D.STAGE_DESIGN: "stage and set design", D.FASHION: "fashion",
    D.ART: "contemporary art", D.TECHNOLOGY: "spatial technology",
    D.ENTERTAINMENT: "production design", D.MOVIES: "film production design",
    D.TV_SERIES: "series production design", D.STREAMING: "streaming production design",
    D.GAMES: "game environment design", D.MUSIC: "live music design",
    D.PHOTOGRAPHY: "photography", D.PRODUCT_DESIGN: "product design",
    D.AUTOMOTIVE: "automotive design", D.NATURE: "biomimetic design",
    D.TRAVEL: "travel design", D.HOSPITALITY: "hospitality design",
    D.SOCIAL_VISUAL_CULTURE: "visual culture", D.BRAND_DESIGN: "brand environments",
    D.EXHIBITIONS: "exhibition design", D.FESTIVALS: "festival design",
    D.CULTURE: "cultural design", D.OTHER: "design",
}

TYPOLOGY_PHRASE = {
    "WEDDING_MANDAP": "wedding ceremony", "EVENT_STAGE": "stage",
    "RESTAURANT": "restaurant", "INTERIOR": "interior",
    "PAVILION": "pavilion", "EXHIBITION": "exhibition", "GENERIC_SPATIAL": "spatial",
}
REGISTER_WORDS = ("luxury", "premium", "minimal", "experimental", "futuristic",
                  "intimate", "dramatic", "sustainable", "bold")


def _register(brief_text: str) -> str:
    low = brief_text.lower()
    return next((w for w in REGISTER_WORDS if w in low), "")


def _material_mood(brief_text: str) -> str:
    low = brief_text.lower()
    for w in ("chrome", "stone", "timber", "textile", "glass", "light", "water",
              "metal", "colour", "color"):
        if w in low:
            return w
    return ""


def build_queries(program: DesignProgram, brief_text: str, plan: list[TrendDomainPlan],
                  mode: TrendMode, region: str | None, today: date) -> list[TrendDomainPlan]:
    year = today.year
    register = _register(brief_text)
    typ = TYPOLOGY_PHRASE.get(program.typology.value, "spatial")
    mood = _material_mood(brief_text)

    out: list[TrendDomainPlan] = []
    for p in plan:
        phrase = DOMAIN_PHRASE[p.domain]
        q: list[str] = [
            " ".join(x for x in (str(year), register, typ, phrase, "trends") if x),
        ]
        if mode is TrendMode.TRENDING_NOW:
            q.append(" ".join(x for x in (str(year), phrase, "emerging now") if x))
        else:
            q.append(" ".join(x for x in (str(year), phrase, mood, "trends") if x))
        # location only when the user actually gave one (§15)
        q.append(" ".join(x for x in ("current", phrase, region or "") if x).strip())
        seen, uniq = set(), []
        for s in q:
            s = re.sub(r"\s{2,}", " ", s).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                uniq.append(s)
        out.append(p.model_copy(update={"queries": uniq[:MAX_QUERIES_PER_DOMAIN]}))
    return out
