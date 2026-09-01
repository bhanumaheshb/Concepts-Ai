"""Search-space instantiation.

Prunes the global ontology down to the region that is *legal* for this brief, so
that impossible concepts are unreachable rather than rejected later. Every removal
is recorded with the rule that caused it, which is what makes "why isn't parametric
an option here?" a machine-answerable question.
"""
from __future__ import annotations

import math

from app.core.ids import deterministic_id
from app.domain.brief import DesignProgram
from app.domain.common import ACTIVE_FACETS
from app.domain.space import (
    CreativeSearchSpace, Exclusion, FacetDomain, TensionPair, ValuePrior,
)
from app.ontology.graph import Ontology

# facet id used inside the genotype -> ontology facet id
FACET_ONTOLOGY = {
    "material_palette": "material",
    "geometry_system": "geometry_system",
}
DEFAULT_AFFINITY = 0.75
LOW_AFFINITY = 0.25


class SpaceCollapsed(RuntimeError):
    def __init__(self, facet: str) -> None:
        super().__init__(f"facet domain emptied: {facet}")
        self.facet = facet


def _ontology_facet(genotype_facet: str) -> str:
    return FACET_ONTOLOGY.get(genotype_facet, genotype_facet)


def _rule_applies(rule: dict, program: DesignProgram) -> bool:
    when = rule.get("when") or {}
    if when.get("always"):
        return True
    if "budget_band_lte" in when and program.budget.band > when["budget_band_lte"]:
        return False
    if "site_kind" in when and program.site.kind != when["site_kind"]:
        return False
    if "rain_risk_gte" in when and program.site.climate.rain_risk < when["rain_risk_gte"]:
        return False
    if "load_in_hours_lte" in when and program.schedule.load_in_hours > when["load_in_hours_lte"]:
        return False
    if "usable_area_lte" in when and program.site.usable_area_m2 > when["usable_area_lte"]:
        return False
    return bool(when)


def _prunes(rule: dict, node, program: DesignProgram) -> bool:
    if "prune_cost_gte" in rule and node.cost >= rule["prune_cost_gte"]:
        return True
    if rule.get("prune_climate_bad") and program.site.climate.label in node.climate_bad:
        return True
    if rule.get("prune_typ_low") and program.typology.value in node.typ_low:
        return True
    if node.id in (rule.get("prune_nodes") or []):
        return True
    return False


def instantiate_space(
    ont: Ontology, program: DesignProgram, disabled_rules: frozenset[str] = frozenset(),
    prior_bias: list | None = None,
) -> CreativeSearchSpace:
    domains: list[FacetDomain] = []
    relaxations: list[str] = []
    bias_by_value: dict[tuple[str, str], float] = {}
    for fp in (prior_bias or []):
        key = (fp.facet_id, fp.value)
        bias_by_value[key] = max(bias_by_value.get(key, 1.0), float(fp.multiplier))
    rules = [r for r in ont.rules() if r.get("kind") != "predicate" and r["id"] not in disabled_rules]

    for facet in ACTIVE_FACETS:
        of = _ontology_facet(facet)
        legal: list[ValuePrior] = []
        excluded: list[Exclusion] = []
        for ref in ont.values(of):
            node = ont.node(ref)
            killer = next(
                (r for r in rules if _rule_applies(r, program) and _prunes(r, node, program)), None
            )
            if killer:
                excluded.append(Exclusion(value=ref, rule_id=killer["id"], reason=killer["reason"]))
                continue
            weight = DEFAULT_AFFINITY
            if program.typology.value in node.typ_low:
                weight = LOW_AFFINITY
            # cheaper values are marginally more likely, so a low budget still has shape
            weight *= 1.0 + (5 - node.cost) * 0.04
            # R-REF-14: reference bias is applied AFTER pruning and only ever RAISES a
            # weight. It never adds to or removes from the legal set — pruning stays the
            # exclusive job of rules.yaml.
            weight *= bias_by_value.get((facet, ref), 1.0)
            legal.append(ValuePrior(value=ref, weight=round(min(4.0, weight), 4)))
        if not legal:
            raise SpaceCollapsed(facet)
        domains.append(FacetDomain(facet_id=facet, legal=legal, excluded=excluded))

    tensions = [
        TensionPair(a=e.src, b=e.dst, weight=e.weight) for e in ont.edges if e.type == "tensions_with"
    ]
    dim = sum(math.log(max(1, len(d.legal))) for d in domains)
    return CreativeSearchSpace(
        space_id=deterministic_id("sp", program.program_id, ont.version, sorted(disabled_rules)),
        program_id=program.program_id,
        ontology_version=ont.version,
        domains=domains,
        tensions=tensions,
        relaxations_applied=relaxations,
        effective_dimensionality=round(dim, 3),
    )


def instantiate_with_relaxation(ont: Ontology, program: DesignProgram,
                                prior_bias: list | None = None) -> CreativeSearchSpace:
    """If a facet domain empties, relax rules in the declared order and record it,
    rather than failing the exploration."""
    disabled: set[str] = set()
    order = ont.relaxation_order()
    for attempt in range(len(order) + 1):
        try:
            space = instantiate_space(ont, program, frozenset(disabled), prior_bias)
            if disabled:
                space = space.model_copy(update={"relaxations_applied": sorted(disabled)})
            return space
        except SpaceCollapsed:
            if attempt >= len(order):
                raise
            disabled.add(order[attempt])
    raise SpaceCollapsed("unknown")
