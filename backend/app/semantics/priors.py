"""Semantic priors and search-space scope, derived from the understood brief.

The creative search is never told what to choose. It is told which values do not
belong to this brief at all (scope — pruned with a recorded reason) and which ones
the brief leans toward (priors — weights raised, nothing made illegal).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.domain.semantics import SemanticBrief
from app.semantics.knowledge import Scope, load_knowledge
from app.semantics.scope import ScopeContext, judge

ROOT = Path(__file__).resolve().parent / "knowledge"


@dataclass(frozen=True)
class SemanticPrior:
    """Same shape as a reference FacetPrior, so the space treats both identically."""
    facet_id: str
    value: str
    multiplier: float
    reason: str


@lru_cache(maxsize=4)
def _priors(version: str = "v1") -> dict:
    return yaml.safe_load((ROOT / version / "priors.yaml").read_text(encoding="utf-8"))


def semantic_priors(sb: SemanticBrief | None, version: str = "v1") -> list[SemanticPrior]:
    if sb is None:
        return []
    data = _priors(version)
    mult = float(data.get("multiplier", 1.5))
    out: dict[tuple[str, str], SemanticPrior] = {}

    def add(ref: str, why: str) -> None:
        facet = ref.split(":", 1)[0]
        out.setdefault((facet, ref), SemanticPrior(facet, ref, mult, why))

    p = sb.profile
    for ref in (data.get("audience_staging") or {}).get(p.audience_relationship, []):
        add(ref, f"audience relationship: {p.audience_relationship}")
    for item in p.primary_activities:
        for ref in (data.get("activity_values") or {}).get(item.key, []):
            add(ref, f"primary activity: {item.key}")
    return list(out.values())


def value_out_of_scope(node, sb: SemanticBrief | None) -> str | None:
    """The reason an ontology value does not belong to this brief, or None.

    An unstated tradition does NOT prune a rite's values: a wedding of unknown rite
    keeps its own vocabulary in the search space. It is elements — things the concept
    would contain — that an unknown tradition withholds.
    """
    if sb is None:
        return None
    scope = Scope(event_types=node.scope_event_types, families=node.scope_families,
                  traditions=node.scope_traditions)
    if scope.is_neutral:
        return None
    verdict = judge(load_knowledge(), scope, ScopeContext.of(sb.profile),
                    tradition_unknown_allows=True)
    return verdict.rule if verdict.status is not None else None
