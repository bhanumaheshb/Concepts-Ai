"""Brief -> DesignProgram.

Deterministic parsing does the load-bearing work: numbers, dimensions, budget band
and typology defaults. The model contributes only the summary and the soft intents,
because those are the parts that are genuinely linguistic.
"""
from __future__ import annotations

import re

from app.core.ids import deterministic_id
from app.domain.brief import (
    BudgetBand, CapacitySpec, ClimateSpec, Constraint, DesignBrief, DesignProgram,
    RequiredZone, RitualProfile, ScheduleSpec, SiteSpec, SoftIntent,
)
from app.domain.common import Typology, VenueType
from app.domain.semantics import ElementStatus, Provenance, SemanticBrief
from app.ontology.graph import Ontology
from app.semantics.programme import capacity_for

# Fallback only. The space form normally comes from Design Intelligence, which knows
# what the event IS; these keywords name space forms, never events. "wedding" and
# "reception" used to live here and silently turned every celebration into a mandap
# and every wedding reception into a hotel lobby.
TYPOLOGY_KEYWORDS: list[tuple[Typology, tuple[str, ...]]] = [
    (Typology.WEDDING_MANDAP, ("mandap",)),
    (Typology.EVENT_STAGE, ("stage", "set design", "keynote")),
    (Typology.RESTAURANT, ("restaurant", "cafe", "café", "bistro", "covers")),
    (Typology.EXHIBITION, ("exhibition", "booth", "gallery", "museum", "trade fair")),
    (Typology.PAVILION, ("pavilion", "installation", "folly", "canopy structure")),
    (Typology.INTERIOR, ("lobby", "interior", "living room", "office", "villa")),
]
# A typology that encodes an EVENT, not only a space form. Selecting it cannot
# override what the brief itself says is happening.
EVENT_LADEN_TYPOLOGY = {Typology.WEDDING_MANDAP: "wedding_ceremony"}
HOT_DRY = ("jaipur", "jodhpur", "rajasthan", "dubai", "delhi", "ahmedabad", "riyadh")
HOT_HUMID = ("mumbai", "chennai", "kochi", "goa", "kolkata", "singapore", "bangkok")
COLD = ("london", "berlin", "oslo", "toronto", "moscow", "zurich")
MONSOON_MONTHS = {6, 7, 8, 9}


def classify_typology(text: str) -> Typology:
    low = text.lower()
    for typ, keys in TYPOLOGY_KEYWORDS:
        if any(k in low for k in keys):
            return typ
    return Typology.GENERIC_SPATIAL


def _first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, re.I)
    return int(m.group(1)) if m else None


def parse_capacity(text: str, default: int) -> int:
    # The adjectival form is at least as common as the noun form in real briefs
    # ("a 500-person sangeeth"), and missing it silently substituted the typology
    # default — the system itself overriding a number the brief stated.
    for pat in (r"(\d[\d,]*)\s*[-\u2013]?\s*(?:guests?|people|persons?|pax|attendees?"
                r"|visitors?|covers?|seats?|seaters?|head)\b",
                r"for\s+(\d[\d,]*)\b"):
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    return default


def parse_dimensions(text: str) -> tuple[float, float] | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:m|metres|meters)?", text, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d[\d,]*)\s*(?:sqm|sq\.?\s?m|square\s+met(?:er|re)s?|m2|m²)", text, re.I)
    if m:
        area = float(m.group(1).replace(",", ""))
        side = round(area ** 0.5, 1)
        return round(side * 1.4, 1), round(side / 1.4, 1)
    return None


def parse_budget_band(text: str) -> int | None:
    low = text.lower()
    if any(w in low for w in ("ultra luxury", "no budget constraint", "unlimited", "opulent")):
        return 5
    if any(w in low for w in ("luxury", "premium", "high-end", "lavish", "flagship")):
        return 4
    if any(w in low for w in ("mid-range", "moderate", "standard")):
        return 3
    if any(w in low for w in ("budget", "affordable", "low cost", "economical", "modest", "tight budget")):
        return 2
    if any(w in low for w in ("minimal budget", "shoestring")):
        return 1
    return None


def parse_climate(text: str, month: int) -> ClimateSpec:
    low = text.lower()
    label = "temperate"
    if any(c in low for c in HOT_DRY):
        label = "hot_dry"
    elif any(c in low for c in HOT_HUMID):
        label = "hot_humid"
    elif any(c in low for c in COLD):
        label = "cold"
    rain = 0.2
    if month in MONSOON_MONTHS and (label in ("hot_humid", "hot_dry") or "monsoon" in low):
        label, rain = "monsoon", 0.75
    if "monsoon" in low or "rain" in low:
        label, rain = "monsoon", max(rain, 0.7)
    return ClimateSpec(label=label, month=month, rain_risk=rain)


def parse_month(text: str) -> int:
    months = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]
    low = text.lower()
    for i, m in enumerate(months, start=1):
        if m in low:
            return i
    return 1


def estimate_capacity(brief: DesignBrief) -> int | None:
    """The crowd the brief states, or None, before any default is applied."""
    text = " ".join(filter(None, [brief.raw_text, brief.constraints_text]))
    n = parse_capacity(text, 0)
    return n or None


def resolve_typology(brief: DesignBrief, semantic: SemanticBrief) -> Typology:
    """Space form. The brief's explicit choice stands unless it names a DIFFERENT event
    than the one the brief describes: a concert submitted as 'Wedding / Mandap'."""
    semantic_typ = _typology(semantic.space_typology)
    if brief.typology == Typology.GENERIC_SPATIAL:
        return semantic_typ
    implied = EVENT_LADEN_TYPOLOGY.get(brief.typology)
    if implied and semantic.profile.identity.event_type != implied:
        return semantic_typ
    return brief.typology


def _typology(value: str) -> Typology:
    try:
        return Typology(value)
    except ValueError:
        return Typology.GENERIC_SPATIAL


def build_program(ont: Ontology, brief: DesignBrief,
                  semantic: SemanticBrief | None = None) -> DesignProgram:
    """Physical facts from the brief and the space form; MEANING from the semantics.

    Typology supplies defaults for things a brief often omits: site size, load-in
    time, a default crowd. It no longer supplies zones, invariants or rites. Those are
    what the event is, and a space form cannot know that.
    """
    text = " ".join(filter(None, [
        brief.raw_text, brief.location, brief.dimensions_text, brief.budget_text, brief.constraints_text
    ]))
    if semantic is None:
        # deterministic reading: every caller gets semantics, with or without a model
        from app.semantics.intelligence import DesignIntelligence
        semantic = DesignIntelligence().understand(brief, capacity=estimate_capacity(brief))
    typology = resolve_typology(brief, semantic)
    defaults = ont.typology_defaults.get(typology.value, ont.typology_defaults["GENERIC_SPATIAL"])

    d_cap = defaults.get("capacity", {})
    guests = parse_capacity(text, int(d_cap.get("guests", 100)))
    capacity = CapacitySpec(
        guests=guests,
        seated=min(guests, int(d_cap.get("seated", guests))) if guests else int(d_cap.get("seated", 60)),
        principals=int(d_cap.get("principals", 0)),
    )

    d_site = defaults.get("site", {})
    dims = parse_dimensions(text)
    # a bigger crowd needs a bigger default plot when the brief gives no dimensions
    scale_factor = max(1.0, (guests / max(1, int(d_cap.get("guests", 100)))) ** 0.5)
    width = dims[0] if dims else round(float(d_site.get("width_m", 28)) * scale_factor, 1)
    depth = dims[1] if dims else round(float(d_site.get("depth_m", 20)) * scale_factor, 1)
    month = parse_month(text)
    site = SiteSpec(
        kind=d_site.get("kind", "OUTDOOR"), width_m=width, depth_m=depth,
        ground=d_site.get("ground", "LAWN"), climate=parse_climate(text, month),
    )

    band = parse_budget_band(text) or 3
    d_sched = defaults.get("schedule", {})
    schedule = ScheduleSpec(
        load_in_hours=float(d_sched.get("load_in_hours", 48)),
        strike_hours=float(d_sched.get("strike_hours", 12)), event_month=month,
    )

    invariants: list[Constraint] = []
    for inv in semantic.invariants:
        invariants.append(Constraint(
            constraint_id=inv.id, kind="HARD",
            category=inv.category if inv.category in _CATEGORIES else "PROGRAM",
            statement=inv.statement, source="SEMANTIC", sacred=inv.sacred,
            confidence=inv.confidence,
        ))
    exclusion = _exclusion_statement(semantic)
    if exclusion:
        invariants.append(Constraint(
            constraint_id="c_semantic_exclusions", kind="HARD", category="PROGRAM",
            statement=exclusion, source="SEMANTIC",
        ))
    invariants.append(Constraint(
        constraint_id="c_capacity", kind="HARD", category="CAPACITY",
        statement=f"The design must accommodate {capacity.guests} people.",
        measurable={"field_path": "program.capacity.guests", "op": "GTE", "value": capacity.guests},
        source="BRIEF" if guests != int(d_cap.get("guests", 100)) else "DEFAULT",
    ))
    invariants.append(Constraint(
        constraint_id="c_site_bounds", kind="HARD", category="SITE",
        statement=f"The design must fit within a {width} x {depth} m site.",
        measurable={"field_path": "program.site.usable_area_m2", "op": "LTE",
                    "value": round(width * depth, 2)},
        source="BRIEF" if dims else "DEFAULT",
    ))
    invariants.append(Constraint(
        constraint_id="c_budget_band", kind="HARD", category="BUDGET",
        statement=f"The design must be deliverable within budget band {band} of 5.",
        measurable={"field_path": "program.budget.band", "op": "LTE", "value": band},
        source="BRIEF" if parse_budget_band(text) else "DEFAULT",
    ))
    invariants.append(Constraint(
        constraint_id="c_loadin", kind="HARD", category="SCHEDULE",
        statement=f"Construction must be completable within a {schedule.load_in_hours:.0f} hour load-in.",
        measurable={"field_path": "program.schedule.load_in_hours", "op": "LTE",
                    "value": schedule.load_in_hours},
        source="DEFAULT",
    ))
    if site.climate.label in ("hot_dry", "monsoon"):
        invariants.append(Constraint(
            constraint_id="c_climate", kind="HARD", category="CLIMATE",
            statement=f"The design must perform in a {site.climate.label.replace('_', ' ')} climate.",
            source="INFERRED",
        ))

    ritual = None
    if semantic.ritual_refs:
        ritual = RitualProfile(tradition=semantic.profile.identity.tradition,
                               region=brief.location,
                               required_elements=list(semantic.ritual_refs))

    # zones: the semantic programme, sized to this site and this crowd
    usable = width * depth
    zones = [RequiredZone(zone=z.key, min_area_m2=round(z.area_share * usable, 1),
                          capacity=capacity_for(z, capacity.guests))
             for z in semantic.programme if z.priority in ("required", "recommended")]

    label = semantic.profile.identity.event_type_label
    return DesignProgram(
        program_id=deterministic_id("pg", brief.brief_id, typology.value),
        brief_id=brief.brief_id, typology=typology,
        event_type=brief.event_type, tradition=brief.tradition,
        venue_type=(brief.venue_type if brief.venue_type != VenueType.UNSPECIFIED
                    else VenueType.CONVENTION_SPACE),
        invariants=invariants, soft_intents=[], open_variables=[],
        site=site, budget=BudgetBand(band=band), schedule=schedule, capacity=capacity,
        ritual=ritual, required_zones=zones, semantic=semantic,
        summary=f"{label} for {capacity.guests} "
                f"on a {width}x{depth} m {site.kind.lower()} site, budget band {band}/5, "
                f"{site.climate.label.replace('_', ' ')} climate.",
    )


_CATEGORIES = {"RITUAL", "SAFETY", "CAPACITY", "BUDGET", "SITE", "SCHEDULE", "CLIMATE",
               "ACCESS", "PROGRAM"}


def _exclusion_statement(semantic: SemanticBrief) -> str:
    """What the concept is NOT, stated once: only what a designer could plausibly
    confuse it with, or what the user excluded by name. A restaurant brief is not
    told it contains no mandap; that would only put the word in front of a model."""
    items = [e.label for e in semantic.profile.elements
             if e.status == ElementStatus.FORBIDDEN
             and (e.provenance == Provenance.USER_EXPLICIT or "neighbouring" in e.rationale)]
    if not items:
        return ""
    label = semantic.profile.identity.event_type_label
    return f"This is a {label}. It must not contain: " + ", ".join(items[:16]) + "."


def attach_soft_intents(program: DesignProgram, proposal_intents: list[str]) -> DesignProgram:
    intents = [
        SoftIntent(intent_id=f"si_{i}", statement=s, weight=0.5)
        for i, s in enumerate(proposal_intents[:5])
    ]
    return program.model_copy(update={"soft_intents": intents})
