"""Scope: where an element — or an ontology value — natively belongs.

This is the single rule behind every negative semantic in the engine. It is applied
identically to programme elements, to genotype values in the search space, and to
text the engine or a model produces, so the three can never disagree about whether
a mandap belongs in a Sangeet.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.semantics import ElementStatus
from app.semantics.knowledge import Element, Knowledge, Scope


@dataclass(frozen=True)
class ScopeContext:
    event_type: str | None
    family: str | None
    tradition: str | None

    @classmethod
    def of(cls, profile) -> "ScopeContext":
        i = profile.identity
        return cls(event_type=i.event_type, family=i.event_family, tradition=i.tradition)


@dataclass(frozen=True)
class ScopeVerdict:
    status: ElementStatus | None      # None => in scope / neutral: no opinion
    rule: str
    near_miss: bool = False           # belongs to a neighbouring event of the same family


def judge(knowledge: Knowledge, scope: Scope, ctx: ScopeContext,
          tradition_unknown_allows: bool = False) -> ScopeVerdict:
    """FORBIDDEN outside scope; CONTEXTUAL when only the tradition is unknown.

    `tradition_unknown_allows` is True for ONTOLOGY VALUES: an unstated tradition must
    not strip a wedding's search space of its own vocabulary. For ELEMENTS it is False,
    so a wedding of unknown rite is not handed a Hindu fire by default.
    """
    if scope.is_neutral:
        return ScopeVerdict(None, "neutral")
    near = _near_miss(knowledge, scope, ctx)
    if scope.event_types and ctx.event_type not in scope.event_types:
        return ScopeVerdict(ElementStatus.FORBIDDEN,
                            f"scope: belongs to {', '.join(scope.event_types)}", near)
    if scope.families and ctx.family not in scope.families:
        return ScopeVerdict(ElementStatus.FORBIDDEN,
                            f"scope: belongs to the {', '.join(scope.families)} family", near)
    if scope.traditions:
        if ctx.tradition is None:
            if tradition_unknown_allows:
                return ScopeVerdict(None, "tradition unstated: allowed as a value")
            return ScopeVerdict(ElementStatus.CONTEXTUAL,
                                f"tradition unstated; belongs to {', '.join(scope.traditions)}",
                                True)
        if ctx.tradition not in scope.traditions:
            return ScopeVerdict(ElementStatus.FORBIDDEN,
                                f"scope: belongs to the {', '.join(scope.traditions)} tradition",
                                True)
    return ScopeVerdict(None, "in scope")


def _near_miss(knowledge: Knowledge, scope: Scope, ctx: ScopeContext) -> bool:
    """Would a careless designer plausibly put this here? True when the element's home
    shares a family with the brief — a mandap in a Sangeet, not a mandap in an office."""
    if not ctx.family:
        return False
    homes = set(scope.families)
    homes |= {knowledge.family_of(t) for t in scope.event_types}
    return ctx.family in homes


def element_verdict(knowledge: Knowledge, el: Element, ctx: ScopeContext) -> ScopeVerdict:
    return judge(knowledge, el.scope, ctx, tradition_unknown_allows=False)
