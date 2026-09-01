"""REF-04 — the injection builder.

Produces the ONLY object Reference Intelligence hands to the creative engine
(R-REF-01). Everything the engine needs is in here; nothing else crosses the boundary.
"""
from __future__ import annotations

from app.core.ids import deterministic_id
from app.core.versions import VersionStamp
from app.domain.antibrief import ClicheCluster
from app.domain.common import ACTIVE_FACETS, NicheRole
from app.domain.reference import (
    CreativePrincipleInjection, FacetPrior, ReferenceDNA, ReferenceRequest, SurfaceLexicon,
)
from app.ontology.graph import Ontology, Principle
from app.references.abstraction import principles_from
from app.references.compatibility import classify
from app.references.influence import resolve_request
from app.references.synthesis import synthesise

# how many concepts of each role the curriculum produces, for dimension distribution
ROLE_SLOTS = {NicheRole.CANONICAL: 1, NicheRole.ADJACENT: 3,
              NicheRole.EXPLORATORY: 4, NicheRole.RADICAL: 1}


def build_injection(
    ont: Ontology, dnas: list[ReferenceDNA], request: ReferenceRequest,
    space=None, seed: int = 0,
) -> CreativePrincipleInjection:
    compat = classify(ont, dnas)
    influence, dimension_filter = resolve_request(request, compat.influence_cap)
    roles = tuple(r.value for r in influence.role_coverage)

    # ── principles ───────────────────────────────────────────────
    if len(dnas) > 1 and request.synthesis:
        principles, abstraction_log, synthesis_log = synthesise(
            ont, dnas, space, influence.abstraction_floor,
            influence.max_principles, roles, seed)
    else:
        principles, abstraction_log, synthesis_log = [], [], []
        for dna in dnas:
            ps, log = principles_from(dna, space, influence.abstraction_floor, roles)
            principles += ps
            abstraction_log += log
        principles.sort(key=lambda p: (-p.salience, p.id))
        principles = principles[: influence.max_principles]

    if dimension_filter:
        allowed = {d.value for d in dimension_filter}
        filtered = [p for p in principles if p.provenance.dimension in allowed]
        principles = filtered or principles[:1]   # never inject nothing at all

    # ── prior bias — R-REF-02 ceiling, R-REF-14 multiply-only ────
    prior_bias: list[FacetPrior] = []
    biased_facets: list[str] = []
    for p in principles:
        for facet, values in sorted(p.biases.items()):
            if facet not in ACTIVE_FACETS:
                continue
            if facet not in biased_facets:
                if len(biased_facets) >= influence.max_biased_facets:
                    continue
                biased_facets.append(facet)
            for v in values:
                prior_bias.append(FacetPrior(
                    facet_id=facet, value=v, multiplier=influence.prior_multiplier,
                    source_reference_id=(p.provenance.reference_ids[0]
                                         if p.provenance.reference_ids else "unknown"),
                ))

    # ── the literal readings become cliché clusters (§0) ─────────
    clusters: list[ClicheCluster] = []
    for dna in dnas:
        lr = dna.literal_reading
        legal = [v for v in lr.facet_values if space is None or _legal_anywhere(space, v)]
        if len(legal) < 2:
            legal = lr.facet_values[:2]
        clusters.append(ClicheCluster(
            cluster_id=deterministic_id("cl", "ref", dna.identity.reference_id),
            label=lr.label, facet_values=legal, prevalence=lr.prevalence,
            evidence="REFERENCE", surface_tokens=list(lr.surface_tokens),
        ))

    lexicon = SurfaceLexicon()
    for dna in dnas:
        lexicon = lexicon.merged_with(dna.surface_lexicon)
    lexicon, collisions = _drop_ontology_collisions(ont, lexicon)

    return CreativePrincipleInjection(
        injection_id=deterministic_id("inj", *[d.identity.reference_id for d in dnas],
                                      str(influence.level), str(seed)),
        principles=principles, prior_bias=prior_bias, cliche_clusters=clusters,
        surface_lexicon=lexicon, influence=influence, compatibility=compat,
        reference_dnas=dnas, abstraction_log=abstraction_log, synthesis_log=synthesis_log,
        niche_assignment=assign_to_niches(principles, influence),
        ontology_collisions=collisions,
        versions=VersionStamp(ontology_version=ont.version),
    )


def _drop_ontology_collisions(ont: Ontology, lexicon: SurfaceLexicon):
    """Never block a token that is the ontology's own vocabulary.

    A reference lexicon is franchise vocabulary; the ontology is design vocabulary. If
    they collide — "mughal" is both a lexicon entry for a palace reference and the label
    of a real architectural_language value — blocking it would forbid the engine from
    naming its own material. The collision is recorded rather than silently dropped.
    """
    ontology_terms: set[str] = set()
    for node in ont.nodes.values():
        # labels, value slugs AND prompt phrases: the prompt phrase is the engine's own
        # output vocabulary, so blocking a word inside one would forbid the compiler
        # from describing a value it legitimately chose
        for source in (node.label, node.value.replace("_", " "), node.phrase or ""):
            low = source.lower()
            if low:
                ontology_terms.add(low)
                ontology_terms.update(w for w in low.replace(",", " ").split() if len(w) > 3)

    kept, collisions = [], []
    for tok in lexicon.tokens:
        low = tok.token.lower()
        collides = low in ontology_terms or (
            len(low) >= 5 and any(term.startswith(low) for term in ontology_terms))
        (collisions if collides else kept).append(tok.token.lower() if collides else tok)
        if collides:
            continue
    return SurfaceLexicon(tokens=[t for t in kept if not isinstance(t, str)]), sorted(set(
        c for c in collisions if isinstance(c, str)))


def _legal_anywhere(space, ref: str) -> bool:
    facet = ref.split(":", 1)[0]
    target = "material_palette" if facet == "material" else facet
    return space.is_legal(target, ref)


def assign_to_niches(principles: list[Principle], influence) -> dict[str, list[str]]:
    """R-REF-20 — distribute across DIFFERENT reference dimensions per niche.

    Four exploratory niches all carrying the highest-salience trait is how a
    reference-mode portfolio collapses into four variations of one idea, and it is
    invisible to the genotype metric because the facets still differ.
    """
    if not principles:
        return {}
    # order so consecutive entries come from different dimensions
    by_dim: dict[str, list[Principle]] = {}
    for p in principles:
        by_dim.setdefault(p.provenance.dimension or "UNKNOWN", []).append(p)
    rotation: list[Principle] = []
    while any(by_dim.values()):
        for dim in sorted(by_dim):
            if by_dim[dim]:
                rotation.append(by_dim[dim].pop(0))

    out: dict[str, list[str]] = {}
    cursor = 0
    for role in influence.role_coverage:
        if role is NicheRole.WILDCARD:            # R-REF-03, belt and braces
            continue
        slots = ROLE_SLOTS.get(role, 1)
        ids: list[str] = []
        used_dims: set[str] = set()
        for _ in range(slots):
            # prefer a dimension this role has not used yet; only repeat once the pool
            # of distinct dimensions is exhausted
            pick = None
            for offset in range(len(rotation)):
                cand = rotation[(cursor + offset) % len(rotation)]
                if (cand.provenance.dimension or "") not in used_dims:
                    pick = cand
                    cursor = (cursor + offset + 1) % len(rotation)
                    break
            if pick is None:
                pick = rotation[cursor % len(rotation)]
                cursor += 1
            used_dims.add(pick.provenance.dimension or "")
            ids.append(pick.id)
        out[role.value] = ids
    out[NicheRole.WILDCARD.value] = []             # explicit: none by design
    return out
