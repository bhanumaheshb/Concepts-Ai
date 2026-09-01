"""Typed genotype operators.

Operators act on the GENOTYPE, never on prose. The phenotype is regenerated
afterwards from the mutated vector — the only way "make it more unexpected" can be
a repeatable operation rather than a rewording.

No operator may touch a pinned facet, an identity facet when `protect` is set, or
anything derived from a sacred constraint (spec R-MUT-01).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from app.core.seeded import SeededRandom
from app.domain.common import IDENTITY_FACETS, MaterialRole
from app.domain.genotype import ConceptGenotype, FacetAssignment, MaterialAssignment
from app.domain.space import CreativeSearchSpace
from app.ontology.graph import Ontology
from app.space.csp import requires_closure

SINGLE_FACET_ATTR = {
    "thesis_archetype": "thesis_archetype",
    "architectural_language": "architectural_language",
    "structural_logic": "structural_logic",
    "occupation_staging": "occupation_staging",
    "lighting_philosophy": "lighting_philosophy",
    "site_relationship": "site_relationship",
    "tectonic_logic": "tectonic_logic",
    "scale_strategy": "scale_strategy",
    "emotional_register": "emotional_register",
}


@dataclass
class MutationOutcome:
    status: str                     # APPLIED | NO_OP | INFEASIBLE | BLOCKED_BY_PIN
    genotype: ConceptGenotype | None
    touched: list[str]
    note: str = ""


@dataclass
class OperatorSpec:
    id: str
    touches: frozenset[str]
    expected: tuple[float, float]
    risk: str
    fn: Callable


def _compatible(ont: Ontology, g: ConceptGenotype, facet: str, value: str) -> bool:
    others = [r for r in g.all_refs() if not r.startswith(facet + ":")]
    return not any(value in ont.excludes(o) or o in ont.excludes(value) for o in others)


def _set_facet(g: ConceptGenotype, facet: str, value: str) -> ConceptGenotype:
    if facet == "geometry_system":
        return g.model_copy(update={"geometry": g.geometry.model_copy(update={"system": value})})
    return g.model_copy(update={SINGLE_FACET_ATTR[facet]: FacetAssignment(value=value)})


def _legal_alternatives(
    ont: Ontology, space: CreativeSearchSpace, g: ConceptGenotype, facet: str,
    exclude_current: bool = True,
) -> list[str]:
    current = g.facet_value(facet)
    out = []
    for v in space.legal(facet):
        if exclude_current and v == current:
            continue
        if _compatible(ont, g, facet, v):
            out.append(v)
    return out


def _refresh_derived(ont: Ontology, g: ConceptGenotype) -> ConceptGenotype:
    return g.model_copy(update={"technology": requires_closure(ont, g.all_refs())})


# ---------------- operators ----------------

def op_invert(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    candidates = [f for f in SINGLE_FACET_ATTR if f not in pinned]
    for facet in rng.shuffled(candidates):
        cur = g.facet_value(facet)
        if not cur:
            continue
        for inv in ont.inverse_of(cur):
            if space.is_legal(facet, inv) and _compatible(ont, g, facet, inv):
                return MutationOutcome("APPLIED", _refresh_derived(ont, _set_facet(g, facet, inv)),
                                       [facet], f"{cur} -> {inv}")
    return MutationOutcome("INFEASIBLE", None, [], "no legal inverse for any unpinned facet")


def op_attenuate(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    touched: list[str] = []
    new = g
    if "scale_strategy" not in pinned:
        order = ont.orders.get("scale_strategy", [])
        idx = ont.rank("scale_strategy", g.scale_strategy.value)
        if idx > 0:
            cand = f"scale_strategy:{order[idx - 1]}"
            if space.is_legal("scale_strategy", cand):
                new = _set_facet(new, "scale_strategy", cand)
                touched.append("scale_strategy")
    if len(new.material_palette) > 2:
        keep = [m for m in new.material_palette if m.role != MaterialRole.FIGURE][:3]
        if len(keep) >= 2 and len(keep) < len(new.material_palette):
            new = new.model_copy(update={"material_palette": keep})
            touched.append("material_palette")
    # swap the primary for a cheaper legal alternative
    primary = new.primary_material()
    cheaper = [v for v in _legal_alternatives(ont, space, new, "material_palette")
               if ont.node(v).cost < ont.node(primary.material).cost]
    if cheaper and "material_palette" not in pinned:
        pick = min(cheaper, key=lambda v: (ont.node(v).cost, v))
        pal = [m.model_copy(update={"material": pick}) if m.role == MaterialRole.PRIMARY else m
               for m in new.material_palette]
        if len({m.material for m in pal}) == len(pal):
            new = new.model_copy(update={"material_palette": pal})
            if "material_palette" not in touched:
                touched.append("material_palette")
    if not touched:
        return MutationOutcome("NO_OP", None, [], "already minimal")
    return MutationOutcome("APPLIED", _refresh_derived(ont, new), touched, "attenuated")


def op_material_substitute(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    if "material_palette" in pinned:
        return MutationOutcome("BLOCKED_BY_PIN", None, [], "material palette pinned")
    primary = g.primary_material()
    need = ont.node(g.structural_logic.value).span or 0.0
    others = {m.material for m in g.material_palette if m.role != MaterialRole.PRIMARY}
    cands = [
        v for v in space.legal("material_palette")
        if v != primary.material and v not in others and _compatible(ont, g, "material_palette", v)
    ]
    if need:
        spanning = [v for v in cands if (ont.node(v).span or 0.0) >= min(need, 8.0)]
        cands = spanning or cands
    if not cands:
        return MutationOutcome("INFEASIBLE", None, [], "no compatible alternative primary")
    cands.sort(key=lambda v: (-(ont.node(v).span or 0.0), ont.node(v).cost, v))
    pick = cands[0] if magnitude < 0.5 else rng.choice(cands[: max(1, len(cands) // 2)])
    pal = [m.model_copy(update={"material": pick}) if m.role == MaterialRole.PRIMARY else m
           for m in g.material_palette]
    new = g.model_copy(update={"material_palette": pal})
    # propagate: the structural system must accept the new primary
    if not _compatible(ont, new, "structural_logic", new.structural_logic.value):
        alts = _legal_alternatives(ont, space, new, "structural_logic")
        if not alts:
            return MutationOutcome("INFEASIBLE", None, [], "no structural system accepts the substitute")
        new = _set_facet(new, "structural_logic", alts[0])
    return MutationOutcome("APPLIED", _refresh_derived(ont, new),
                           ["material_palette", "structural_logic"], f"{primary.material} -> {pick}")


def op_transpose(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    """Hold geometry and structure; resample material and tectonic wholesale."""
    if "tectonic_logic" in pinned and "material_palette" in pinned:
        return MutationOutcome("BLOCKED_BY_PIN", None, [], "both target facets pinned")
    new = g
    touched: list[str] = []
    if "tectonic_logic" not in pinned:
        alts = _legal_alternatives(ont, space, g, "tectonic_logic")
        if alts:
            new = _set_facet(new, "tectonic_logic", rng.choice(alts))
            touched.append("tectonic_logic")
    sub = op_material_substitute(ont, space, new, rng.substream("tr"), pinned, magnitude)
    if sub.status == "APPLIED" and sub.genotype is not None:
        new = sub.genotype
        touched += [t for t in sub.touched if t not in touched]
    if not touched:
        return MutationOutcome("INFEASIBLE", None, [], "nothing transposable")
    return MutationOutcome("APPLIED", _refresh_derived(ont, new), touched, "transposed")


def op_reinterpret(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    """Pin the identity facets; resample every other active facet."""
    protected = set(pinned) | IDENTITY_FACETS
    new = g
    touched: list[str] = []
    for facet in ("architectural_language", "geometry_system", "structural_logic",
                  "tectonic_logic", "site_relationship", "occupation_staging",
                  "lighting_philosophy", "scale_strategy"):
        if facet in protected:
            continue
        alts = _legal_alternatives(ont, space, new, facet)
        if not alts:
            continue
        new = _set_facet(new, facet, rng.choice(alts))
        touched.append(facet)
    if not touched:
        return MutationOutcome("INFEASIBLE", None, [], "nothing resampleable")
    return MutationOutcome("APPLIED", _refresh_derived(ont, new), touched, "reinterpreted")


def op_abstract(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    if not g.cultural_lineage:
        return MutationOutcome("NO_OP", None, [], "no cultural references to abstract")
    lineage = [c.model_copy(update={"abstraction": min(1.0, max(c.abstraction, 0.85))})
               for c in g.cultural_lineage]
    return MutationOutcome("APPLIED", g.model_copy(update={"cultural_lineage": lineage}),
                           ["cultural_lineage"], "abstraction raised")


def op_re_ritualise(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    if "occupation_staging" in pinned:
        return MutationOutcome("BLOCKED_BY_PIN", None, [], "staging pinned")
    alts = _legal_alternatives(ont, space, g, "occupation_staging")
    if not alts:
        return MutationOutcome("INFEASIBLE", None, [], "no alternative staging")
    return MutationOutcome("APPLIED", _refresh_derived(ont, _set_facet(g, "occupation_staging", rng.choice(alts))),
                           ["occupation_staging"], "re-staged")


def op_scale_up(ont, space, g, rng, pinned, magnitude) -> MutationOutcome:
    if "scale_strategy" in pinned:
        return MutationOutcome("BLOCKED_BY_PIN", None, [], "scale pinned")
    order = ont.orders.get("scale_strategy", [])
    idx = ont.rank("scale_strategy", g.scale_strategy.value)
    if idx + 1 >= len(order):
        return MutationOutcome("NO_OP", None, [], "already at maximum scale")
    cand = f"scale_strategy:{order[idx + 1]}"
    if not space.is_legal("scale_strategy", cand):
        return MutationOutcome("INFEASIBLE", None, [], "larger scale illegal in this space")
    return MutationOutcome("APPLIED", _set_facet(g, "scale_strategy", cand), ["scale_strategy"], "scaled up")


def op_hybridise(ont, space, a, b, rng, pinned) -> MutationOutcome:
    """FORM group from A, EXPERIENCE group from B; materials union-then-trim."""
    new = a.model_copy(update={
        "occupation_staging": b.occupation_staging,
        "lighting_philosophy": b.lighting_philosophy,
        "emotional_register": b.emotional_register,
        "spatial_narrative": list(b.spatial_narrative),
    })
    for facet in ("occupation_staging", "lighting_philosophy", "emotional_register"):
        v = new.facet_value(facet)
        if v and not _compatible(ont, new, facet, v):
            alts = _legal_alternatives(ont, space, new, facet)
            if not alts:
                return MutationOutcome("INFEASIBLE", None, [], f"irreconcilable at {facet}")
            new = _set_facet(new, facet, alts[0])
    # materials: A primary, B's strongest non-primary as secondary
    b_extra = next((m for m in b.material_palette if m.role != MaterialRole.PRIMARY), None)
    pal = list(a.material_palette)
    if b_extra and b_extra.material not in {m.material for m in pal} and _compatible(
        ont, new, "material_palette", b_extra.material
    ):
        pal = pal[:2] + [b_extra.model_copy(update={"role": MaterialRole.ACCENT, "share": 0.12})]
    new = new.model_copy(update={"material_palette": pal})
    return MutationOutcome("APPLIED", _refresh_derived(ont, new),
                           ["occupation_staging", "lighting_philosophy", "emotional_register",
                            "spatial_narrative", "material_palette"], "hybridised")


REGISTRY: dict[str, OperatorSpec] = {
    "invert": OperatorSpec("invert", frozenset(SINGLE_FACET_ATTR), (0.25, 0.40), "MEDIUM", op_invert),
    "attenuate": OperatorSpec("attenuate", frozenset({"scale_strategy", "material_palette"}),
                              (0.08, 0.15), "LOW", op_attenuate),
    "material_substitute": OperatorSpec("material_substitute",
                                        frozenset({"material_palette", "structural_logic"}),
                                        (0.15, 0.25), "LOW", op_material_substitute),
    "transpose": OperatorSpec("transpose", frozenset({"material_palette", "tectonic_logic"}),
                              (0.20, 0.32), "LOW", op_transpose),
    "reinterpret": OperatorSpec("reinterpret", frozenset(SINGLE_FACET_ATTR), (0.40, 0.60), "MEDIUM",
                                op_reinterpret),
    "abstract": OperatorSpec("abstract", frozenset({"cultural_lineage"}), (0.0, 0.05), "LOW", op_abstract),
    "re_ritualise": OperatorSpec("re_ritualise", frozenset({"occupation_staging"}), (0.20, 0.30),
                                 "MEDIUM", op_re_ritualise),
    "scale_up": OperatorSpec("scale_up", frozenset({"scale_strategy"}), (0.03, 0.06), "LOW", op_scale_up),
}


def apply_operator(
    op_id: str, ont: Ontology, space: CreativeSearchSpace, g: ConceptGenotype,
    rng: SeededRandom, pinned: set[str], magnitude: float = 0.5,
) -> MutationOutcome:
    spec = REGISTRY.get(op_id)
    if spec is None:
        return MutationOutcome("INFEASIBLE", None, [], f"unknown operator {op_id}")
    return spec.fn(ont, space, g, rng, pinned, magnitude)
