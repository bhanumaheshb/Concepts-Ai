"""Cross-domain principle selection.

Principles are selected and applied BEFORE the genotype is solved, so they shape a
concept's coordinates rather than its adjectives. Injecting them after the genotype
is fixed is what produces "stepwell-themed mandap" instead of a transformed idea.
"""
from __future__ import annotations

from app.core.seeded import SeededRandom
from app.domain.common import NicheRole
from app.domain.genotype import ConceptGenotype
from app.domain.space import CreativeSearchSpace
from app.ontology.graph import Ontology, Principle

FAR_T = 0.45
ELIGIBLE_ROLES = {NicheRole.EXPLORATORY, NicheRole.RADICAL}


def _language_domain_class(ont: Ontology, language_ref: str) -> str:
    parent = ont.node(language_ref).parent or ""
    if "indian_traditional" in parent or "asian_traditional" in parent:
        return "ARCHITECTURE_HISTORIC"
    if "vernacular" in parent:
        return "CRAFT"
    if "cinematic" in parent:
        return "CINEMA"
    if "experimental" in parent:
        return "ENGINEERING"
    return "ARCHITECTURE_HISTORIC"


def domain_distance(ont: Ontology, principle: Principle, canonical: ConceptGenotype | None) -> float:
    if canonical is None:
        return 0.6
    canon_class = _language_domain_class(ont, canonical.architectural_language.value)
    return ont.principle_domain_distance(principle.domain_class, canon_class)


def eligible_principles(
    ont: Ontology,
    space: CreativeSearchSpace,
    open_facets: set[str],
    canonical: ConceptGenotype | None,
) -> list[Principle]:
    out: list[Principle] = []
    for p in ont.principles.values():
        if not (set(p.mappable_to) & open_facets):
            continue
        # every bias must be reachable in this pruned space, or the principle cannot attach
        reachable = True
        for facet, values in p.biases.items():
            if facet not in [d.facet_id for d in space.domains]:
                continue
            if not [v for v in values if space.is_legal(facet, v)]:
                reachable = False
                break
        if not reachable:
            continue
        if domain_distance(ont, p, canonical) < FAR_T:
            continue          # far in the graph, but mappable — that is the whole trick
        out.append(p)
    return sorted(out, key=lambda p: p.id)


def select_principle(
    ont: Ontology,
    space: CreativeSearchSpace,
    role: NicheRole,
    open_facets: set[str],
    canonical: ConceptGenotype | None,
    usage: dict[str, int],
    rng: SeededRandom,
) -> Principle | None:
    if role not in ELIGIBLE_ROLES:
        return None
    pool = eligible_principles(ont, space, open_facets, canonical)
    if not pool:
        return None
    total_uses = max(1, sum(usage.values()))
    scored: list[tuple[float, Principle]] = []
    for p in pool:
        usage_rate = usage.get(p.id, 0) / total_uses
        score = (
            0.50 * domain_distance(ont, p, canonical)
            + 0.30 * (1.0 - usage_rate)        # stops one principle recurring in every portfolio
            + 0.20 * 0.75
        )
        scored.append((score, p))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    top = [p for _, p in scored[:5]]
    weights = [max(0.05, s) for s, _ in scored[:5]]
    return rng.weighted_choice(top, weights)


MAX_OVERRIDDEN_FACETS = 2


def principle_overrides(
    ont: Ontology, space: CreativeSearchSpace, principle: Principle | None, pinned: set[str]
) -> dict[str, list[str]]:
    """Restrict facet domains — never expand them.

    Capped at two facets. A principle that pins four facets to two or three values each
    collapses every exploratory niche into the same small region, and they then fail to
    clear D_MIN against one another. Two facets is enough for the principle to shape the
    concept while leaving the rest of the genotype free to diverge.
    """
    if principle is None:
        return {}
    candidates: list[tuple[int, str, list[str]]] = []
    for facet, values in principle.biases.items():
        if facet in pinned:
            continue
        legal = [v for v in values if space.is_legal(facet, v)]
        if legal:
            candidates.append((len(legal), facet, legal))
    # prefer the facets with the most room left, so the restriction bites least
    candidates.sort(key=lambda t: (-t[0], t[1]))
    return {facet: legal for _, facet, legal in candidates[:MAX_OVERRIDDEN_FACETS]}
