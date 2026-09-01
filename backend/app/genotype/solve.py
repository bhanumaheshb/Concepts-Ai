"""Genotype solving.

The genotype is SOLVED as a constraint problem, never written by a language model.
Values are drawn from the pruned search space with seeded, prior-weighted sampling,
checked against `excludes` as they are assigned, and boosted by `implies` edges so
that a concept is internally coherent before a single word of it is written.
"""
from __future__ import annotations

from app.core.seeded import SeededRandom
from app.domain.common import MaterialRole, NicheRole
from app.domain.genotype import (
    ConceptGenotype, CulturalReference, FacetAssignment, GeometrySpec,
    MaterialAssignment, NumericParam, PartialGenotype,
)
from app.domain.space import CreativeSearchSpace
from app.ontology.graph import Ontology
from app.space.csp import requires_closure

# Assignment order: the heaviest, most constraining facets first.
SOLVE_ORDER = [
    "architectural_language",
    "geometry_system",
    "structural_logic",
    "tectonic_logic",
    "site_relationship",
    "thesis_archetype",
    "occupation_staging",
    "lighting_philosophy",
    "scale_strategy",
    "emotional_register",
]
SINGLE_FACETS = SOLVE_ORDER


class SolveFailed(RuntimeError):
    pass


def _pool(
    ont: Ontology,
    space: CreativeSearchSpace,
    facet: str,
    chosen: dict[str, str],
    forbidden: set[str],
    overrides: dict[str, list[str]],
    boosts: dict[str, float],
    cliche_values: set[str],
    cliche_bonus: float,
    uniform: bool,
) -> tuple[list[str], list[float]]:
    """Build the candidate pool for one facet.

    Constraints are applied in priority order and RELAXED rather than allowed to empty
    the domain: `excludes` is physics and never yields; a principle override is the
    concept's identity and yields only to `excludes`; the niche's forbidden set is a
    divergence preference and yields first. An empty domain here means the solver fails
    for every candidate, which silently costs a whole niche.
    """
    domain = space.domain(facet)
    picked = set(chosen.values())
    override = [v for v in overrides.get(facet, []) if v]

    def build(use_forbidden: bool, use_override: bool) -> tuple[list[str], list[float]]:
        values, weights = [], []
        for vp in domain.legal:
            ref = vp.value
            if use_forbidden and ref in forbidden:
                continue
            if use_override and override and ref not in override:
                continue
            if any(ref in ont.excludes(c) for c in picked):
                continue                       # excludes is physics: never relaxed
            w = 1.0 if uniform else vp.weight
            w *= boosts.get(ref, 1.0)
            if ref in cliche_values:
                w *= (1.0 + cliche_bonus)
            values.append(ref)
            weights.append(max(0.0001, w))
        return values, weights

    for use_forbidden, use_override in ((True, True), (False, True), (True, False), (False, False)):
        values, weights = build(use_forbidden, use_override)
        if values:
            return values, weights
    return [], []


def _apply_implies(ont: Ontology, ref: str, boosts: dict[str, float]) -> None:
    for target, w in ont.implies(ref):
        boosts[target] = boosts.get(target, 1.0) * (1.0 + w)


def _geometry_params(ont: Ontology, system: str, scale: str, rng: SeededRandom) -> list[NumericParam]:
    prim = ont.node(system).primitive
    rank = ont.rank("scale_strategy", scale)
    base = 6.0 + rank * 3.0
    if prim == "STEPPED_REVOLVE":
        return [NumericParam(name="tiers", value=float(rng.randint(4, 9)), unit="count"),
                NumericParam(name="rise_m", value=round(0.25 + rng.random() * 0.25, 2), unit="m"),
                NumericParam(name="radius_m", value=round(base * 0.8, 1), unit="m")]
    if prim == "COLONNADE":
        return [NumericParam(name="bays", value=float(rng.randint(4, 12)), unit="count"),
                NumericParam(name="bay_m", value=round(2.0 + rng.random() * 2.0, 2), unit="m")]
    if prim in ("CATENARY_SURFACE", "SHELL_VAULT", "MAST_AND_CABLE"):
        return [NumericParam(name="span_m", value=round(base * 1.4, 1), unit="m"),
                NumericParam(name="rise_m", value=round(2.5 + rng.random() * 4.0, 1), unit="m")]
    if prim == "STACKED_MASS":
        return [NumericParam(name="layers", value=float(rng.randint(3, 7)), unit="count"),
                NumericParam(name="layer_h_m", value=round(0.6 + rng.random() * 0.8, 2), unit="m")]
    return [NumericParam(name="module_m", value=round(1.2 + rng.random() * 2.4, 2), unit="m"),
            NumericParam(name="extent_m", value=round(base, 1), unit="m")]


def _materials(
    ont: Ontology, space: CreativeSearchSpace, chosen: dict[str, str],
    primary_hint: str | None, forbidden: set[str], rng: SeededRandom,
    boosts: dict[str, float] | None = None,
) -> list[MaterialAssignment]:
    domain = space.domain("material_palette")
    picked = set(chosen.values())
    boosts = boosts or {}
    legal = [
        vp.model_copy(update={"weight": min(1.0, vp.weight * boosts.get(vp.value, 1.0))})
        for vp in domain.legal
        if vp.value not in forbidden and not any(vp.value in ont.excludes(c) for c in picked)
    ]
    if not legal:
        raise SolveFailed("no legal material")
    if primary_hint and any(vp.value == primary_hint for vp in legal):
        primary = primary_hint
    else:
        # a PRIMARY must be able to carry the structure: prefer real span capacity
        struct = chosen.get("structural_logic")
        need = ont.node(struct).span if struct and ont.node(struct).span else 0.0
        cands = [vp for vp in legal if (ont.node(vp.value).span or 0.0) >= min(need, 4.0)] or legal
        primary = rng.weighted_choice([c.value for c in cands], [c.weight for c in cands])
    rest = [vp for vp in legal if vp.value != primary
            and primary not in ont.excludes(vp.value)
            and vp.value not in ont.excludes(primary)]
    n_extra = rng.randint(1, min(3, max(1, len(rest))))
    extras = rng.sample_without_replacement([v.value for v in rest], [v.weight for v in rest], n_extra)
    roles = [MaterialRole.SECONDARY, MaterialRole.ACCENT, MaterialRole.FIGURE]
    shares = [0.55, 0.22, 0.12, 0.06]
    out = [MaterialAssignment(material=primary, role=MaterialRole.PRIMARY, share=shares[0])]
    for i, m in enumerate(extras):
        out.append(MaterialAssignment(material=m, role=roles[i % len(roles)], share=shares[i + 1]))
    return out


def _narrative(
    ont: Ontology, space: CreativeSearchSpace, overrides: dict[str, list[str]],
    forbidden: set[str], rng: SeededRandom, hint: list[str] | None,
) -> list[str]:
    if hint:
        return list(hint)[:3]
    domain = space.domain("spatial_narrative")
    pool = [vp for vp in domain.legal if vp.value not in forbidden]
    ov = overrides.get("spatial_narrative") or []
    biased = [vp for vp in pool if vp.value in ov]
    n = rng.randint(2, 3)
    chosen: list[str] = []
    if biased:
        chosen.append(rng.weighted_choice([v.value for v in biased], [v.weight for v in biased]))
    remaining = [vp for vp in pool if vp.value not in chosen]
    chosen += rng.sample_without_replacement(
        [v.value for v in remaining], [v.weight for v in remaining], n - len(chosen)
    )
    return chosen[:3]


def solve_genotype(
    ont: Ontology,
    space: CreativeSearchSpace,
    rng: SeededRandom,
    *,
    skeleton: PartialGenotype | None = None,
    forbidden: set[str] | None = None,
    domain_override: dict[str, list[str]] | None = None,
    cliche_values: set[str] | None = None,
    cliche_bonus: float = 0.0,
    uniform: bool = False,
    max_attempts: int = 6,
) -> ConceptGenotype:
    skeleton = skeleton or PartialGenotype()
    forbidden = set(forbidden or ())
    overrides = dict(domain_override or {})
    cliches = set(cliche_values or ())
    fixed = skeleton.assigned()

    last_error = "unknown"
    for attempt in range(max_attempts):
        r = rng.substream("solve", attempt)
        chosen: dict[str, str] = {}
        boosts: dict[str, float] = {}
        ok = True
        for facet in SOLVE_ORDER:
            if facet in fixed and isinstance(fixed[facet], str):
                ref = str(fixed[facet])
                if any(ref in ont.excludes(c) for c in chosen.values()):
                    ok, last_error = False, f"skeleton conflict at {facet}"
                    break
                chosen[facet] = ref
                _apply_implies(ont, ref, boosts)
                continue
            values, weights = _pool(
                ont, space, facet, chosen, forbidden, overrides, boosts, cliches, cliche_bonus, uniform
            )
            if not values:
                ok, last_error = False, f"no legal value for {facet}"
                break
            ref = r.weighted_choice(values, weights)
            chosen[facet] = ref
            _apply_implies(ont, ref, boosts)
        if not ok:
            continue

        try:
            materials = _materials(
                ont, space, chosen, str(fixed.get("material_primary") or "") or None,
                forbidden, r, boosts,
            )
        except SolveFailed as exc:
            last_error = str(exc)
            continue

        narrative = _narrative(
            ont, space, overrides, forbidden, r,
            list(fixed.get("spatial_narrative") or []) or None,  # type: ignore[arg-type]
        )
        geometry = GeometrySpec(
            system=chosen["geometry_system"],
            params=_geometry_params(ont, chosen["geometry_system"], chosen["scale_strategy"], r),
        )
        all_refs = list(chosen.values()) + [m.material for m in materials] + narrative
        lineage = [
            CulturalReference(ref=chosen["architectural_language"],
                              abstraction=max(0.6, ont.node(chosen["architectural_language"]).min_abstraction),
                              attribution="REGIONAL_TYPOLOGY")
        ] if ont.node(chosen["architectural_language"]).sensitivity != "none" else []

        return ConceptGenotype(
            thesis_archetype=FacetAssignment(value=chosen["thesis_archetype"]),
            architectural_language=FacetAssignment(value=chosen["architectural_language"]),
            geometry=geometry,
            structural_logic=FacetAssignment(value=chosen["structural_logic"]),
            material_palette=materials,
            spatial_narrative=narrative,
            occupation_staging=FacetAssignment(value=chosen["occupation_staging"]),
            lighting_philosophy=FacetAssignment(value=chosen["lighting_philosophy"]),
            site_relationship=FacetAssignment(value=chosen["site_relationship"]),
            tectonic_logic=FacetAssignment(value=chosen["tectonic_logic"]),
            scale_strategy=FacetAssignment(value=chosen["scale_strategy"]),
            emotional_register=FacetAssignment(value=chosen["emotional_register"]),
            cultural_lineage=lineage,
            technology=requires_closure(ont, all_refs),
            anti_attributes=sorted(forbidden)[:8],
        )
    raise SolveFailed(last_error)
