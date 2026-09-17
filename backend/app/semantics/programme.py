"""Programme inference: zones from what happens, not from what the event is called.

    event-type zones  ∪  activity zones  ∪  element zones  ∪  universal zones

Every zone carries the provenance of whatever introduced it. Shares are normalised
deterministically so the programme always fits the site and always holds the crowd —
the two conditions the alignment critic enforces.
"""
from __future__ import annotations

import math

from app.domain.semantics import (
    ElementStatus, EventProfile, ProgramZone, Provenance, SemanticElement,
)
from app.semantics.knowledge import Knowledge, ZoneSpec

MAX_AREA = 0.85            # the rest of the site is structure, margins and slack
PEOPLE_ROLES = ("audience", "participation", "social", "dining", "display", "retail",
                "work", "hospitality")
ROLE_ORDER = ("arrival", "ceremony", "performance", "focal", "participation", "audience",
              "display", "dining", "social", "hospitality", "retail", "work", "media",
              "support", "circulation", "technical", "backstage", "service", "outdoor")
_RANK = {"required": 0, "recommended": 1, "optional": 2}
SERVICE_THRESHOLD = 150    # above this crowd a dedicated service zone is not optional


def _pz(spec: ZoneSpec, provenance: Provenance, rationale: str,
        activity: str | None = None, priority: str | None = None) -> ProgramZone:
    return ProgramZone(key=spec.key, label=spec.label, role=spec.role,
                       priority=priority or spec.priority,
                       area_share=spec.area_share, capacity_share=spec.capacity_share,
                       provenance=provenance, rationale=rationale, activity=activity)


class _Builder:
    def __init__(self) -> None:
        self.zones: dict[str, ProgramZone] = {}

    def add(self, z: ProgramZone, relabel: bool = False) -> None:
        cur = self.zones.get(z.key)
        if cur is None:
            self.zones[z.key] = z
            return
        update: dict = {}
        if _RANK[z.priority] < _RANK[cur.priority]:
            update["priority"] = z.priority
        # a more specific element names the zone: ceremony_focus -> "Mandap"
        if relabel and z.label != cur.label:
            update["label"] = z.label
            update["rationale"] = f"{cur.rationale}; named by {z.rationale}".strip("; ")
        update["area_share"] = max(cur.area_share, z.area_share)
        update["capacity_share"] = max(cur.capacity_share, z.capacity_share)
        self.zones[z.key] = cur.model_copy(update=update)

    def drop(self, key: str) -> None:
        self.zones.pop(key, None)


def infer_programme(knowledge: Knowledge, profile: EventProfile, *,
                    capacity: int | None, explicit_activities: set[str],
                    llm_zones: list[ProgramZone] | None = None) -> list[ProgramZone]:
    b = _Builder()
    et = knowledge.event_types.get(profile.identity.event_type)

    # 1. activities — primary zones at full priority, secondary ones softened unless
    #    the user named the activity themselves
    for items, primary in ((profile.primary_activities, True),
                           (profile.secondary_activities, False)):
        for item in items:
            act = knowledge.activities.get(item.key)
            if act is None:
                continue
            grounded = any(i.provenance in (Provenance.USER_EXPLICIT, Provenance.DOMAIN_KNOWLEDGE)
                           for i in profile.primary_activities)
            for spec in act.zones:
                prio = spec.priority
                if not primary and item.key not in explicit_activities and prio == "required":
                    prio = "recommended"
                # a model's inference suggests a zone; only the brief or the knowledge
                # base can make one part of the built programme
                if item.provenance == Provenance.LLM_INFERENCE and grounded:
                    prio = "optional"
                b.add(_pz(spec, item.provenance,
                          f"implied by {act.label.lower()}", activity=act.key, priority=prio))

    # 2. zones the event type states directly
    if et is not None:
        for spec in et.zones:
            b.add(_pz(spec, Provenance.DOMAIN_KNOWLEDGE, f"part of a {et.label.lower()}"))

    # 3. elements that materialise as zones. Order matters for naming: domain
    #    knowledge first, then user-explicit, so the most specific label wins.
    # A rite's element is more specific than its event's generic one, so it names
    # the zone last: the ceremony focus of a Christian wedding is the Altar.
    def _specificity(e: SemanticElement) -> tuple:
        sc = knowledge.elements[e.key].scope if e.key in knowledge.elements else None
        spec = (2 if sc and sc.traditions else 0) + (1 if sc and (sc.event_types or sc.families) else 0)
        return (e.provenance == Provenance.USER_EXPLICIT, spec, e.key)
    ordered = sorted(profile.elements, key=_specificity)
    for el in ordered:
        spec = knowledge.elements[el.key].zone if el.key in knowledge.elements else None
        if spec is None:
            continue
        if el.status == ElementStatus.FORBIDDEN:
            continue
        prio = {ElementStatus.REQUIRED: "required", ElementStatus.RECOMMENDED: "recommended",
                ElementStatus.OPTIONAL: "optional"}.get(el.status)
        if prio is None:                        # CONTEXTUAL never becomes a zone
            continue
        b.add(_pz(spec, el.provenance, f"{el.label.lower()} ({el.status.value.lower()})",
                  priority=prio), relabel=True)

    # 4. zones the reasoning model proposed (already leak-checked by the caller)
    for z in llm_zones or []:
        b.add(z)

    # 5. forbidden elements take their zones with them — including a zone a model or an
    #    activity introduced — so "no bar" means no bar zone
    for el in profile.elements:
        if el.status != ElementStatus.FORBIDDEN or el.key not in knowledge.elements:
            continue
        spec = knowledge.elements[el.key].zone
        if spec and spec.key in b.zones and _owned_only_by(b.zones[spec.key], el, knowledge):
            b.drop(spec.key)

    # 6. universals — every occupied place is arrived at and moved through
    # only zones that will be built count: an optional suggestion is not an arrival
    roles = {z.role for z in b.zones.values() if z.priority != "optional"}
    if "arrival" not in roles:
        b.add(ProgramZone(key="arrival", label="Arrival", role="arrival", area_share=0.05,
                          provenance=Provenance.DETERMINISTIC_RULE,
                          rationale="every occupied space has an arrival"))
    if "circulation" not in roles:
        b.add(ProgramZone(key="circulation", label="Circulation", role="circulation",
                          area_share=0.08, provenance=Provenance.DETERMINISTIC_RULE,
                          rationale="every occupied space is moved through"))
    if (capacity or 0) >= SERVICE_THRESHOLD and "service" not in roles:
        b.add(ProgramZone(key="service", label="Service and back-of-house", role="service",
                          priority="recommended", area_share=0.05,
                          provenance=Provenance.DETERMINISTIC_RULE,
                          rationale=f"a crowd of {capacity} needs a service zone"))

    return _normalise(list(b.zones.values()))


def _owned_only_by(zone: ProgramZone, el: SemanticElement, knowledge: Knowledge) -> bool:
    """Drop a zone for a forbidden element only when that element is what the zone IS.
    Forbidding a mandap must not remove the ceremony focus of a Christian wedding."""
    spec = knowledge.elements[el.key].zone
    if spec is None:
        return False
    if el.provenance == Provenance.USER_EXPLICIT:
        return True                          # the user excluded it by name
    return zone.label == spec.label


def _normalise(zones: list[ProgramZone]) -> list[ProgramZone]:
    active = [z for z in zones if z.priority != "optional"]
    total_area = sum(z.area_share for z in active)
    area_k = MAX_AREA / total_area if total_area > MAX_AREA else 1.0

    people = [z for z in active if z.role in PEOPLE_ROLES]
    people_keys = {z.key for z in people}
    cap_total = sum(z.capacity_share for z in people)
    cap_k = 1.0
    boost: dict[str, float] = {}
    if people and cap_total < 1.0:
        if cap_total > 0:
            cap_k = 1.0 / cap_total
        else:
            # nobody was given the crowd: spread it over people zones by area
            area = sum(z.area_share for z in people) or 1.0
            boost = {z.key: z.area_share / area for z in people}

    out: list[ProgramZone] = []
    for z in zones:
        upd: dict = {"area_share": round(z.area_share * (area_k if z.priority != "optional" else 1.0), 4)}
        if z.key in people_keys:
            cs = boost.get(z.key, z.capacity_share * cap_k)
            upd["capacity_share"] = round(min(1.0, cs), 4)
        out.append(z.model_copy(update=upd))

    if not people:
        # a programme with no place for people cannot hold the crowd — say so structurally
        out.append(ProgramZone(key="gathering", label="Gathering", role="social",
                               area_share=0.25, capacity_share=1.0,
                               provenance=Provenance.DETERMINISTIC_RULE,
                               rationale="no zone was assigned the crowd"))

    order = {r: i for i, r in enumerate(ROLE_ORDER)}
    out.sort(key=lambda z: (_RANK[z.priority], order.get(z.role, 99), z.key))
    return out


def capacity_for(zone: ProgramZone, guests: int) -> int:
    return int(math.ceil(zone.capacity_share * guests)) if zone.capacity_share else 0
