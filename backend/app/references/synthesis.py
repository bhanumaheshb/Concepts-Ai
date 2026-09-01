"""REF-03 — multi-reference synthesis.

Operates at the level of TRAITS WITHIN A DIMENSION, because that is where two
references actually agree, complement or collide. A union of principle lists is not
synthesis; it is concatenation.

A synthesised principle's source_domain is a NEW abstract label and must never be
"A + B" (R-REF-12).
"""
from __future__ import annotations

import re

from app.core.ids import deterministic_id
from app.core.seeded import SeededRandom
from app.domain.reference import (
    AbstractionRecord, ReferenceDNA, ReferenceDimension, SynthesisRelation, TraitConflict,
)
from app.ontology.graph import Ontology, Principle, PrincipleProvenance
from app.references.abstraction import (
    RUNTIME_PREFIX, _abstract_label, _domain_class_for, abstract_trait, build_biases,
    map_facets,
)
from app.references.compatibility import _edge_between


def _merge_statements(a: str, b: str, relation: SynthesisRelation) -> str:
    a, b = a.rstrip(" .;"), b.rstrip(" .;")
    if relation is SynthesisRelation.REINFORCE:
        return f"{a}, and {_tail(b)}"
    if relation is SynthesisRelation.BRIDGE:
        return f"{a}, and in the same move {_tail(b)}"
    if relation is SynthesisRelation.TENSION_HOLD:
        return f"{a}, while at the same time {_tail(b)}"
    return a          # SUBSUME keeps the more abstract statement


def _tail(s: str) -> str:
    return re.sub(r"^(a|an|the)\s+", "", s.strip(), flags=re.I)


def synthesise(
    ont: Ontology, dnas: list[ReferenceDNA], space, abstraction_floor: float,
    max_principles: int, role_eligibility: tuple[str, ...] | None, seed: int = 0,
) -> tuple[list[Principle], list[AbstractionRecord], list[TraitConflict]]:
    """Returns (principles, abstraction log, synthesis log)."""
    rng = SeededRandom(seed, "synthesis")
    log: list[AbstractionRecord] = []
    decisions: list[TraitConflict] = []

    # 1 — cluster by DIMENSION, not by reference
    buckets: dict[ReferenceDimension, list[tuple[ReferenceDNA, object]]] = {}
    for dna in dnas:
        for t in dna.traits:
            buckets.setdefault(t.dimension, []).append((dna, t))

    out: list[Principle] = []
    for dim in sorted(buckets, key=lambda d: d.value):
        entries = buckets[dim]
        sources = {d.identity.reference_id for d, _ in entries}

        if len(sources) == 1:
            dna, trait = max(entries, key=lambda e: e[1].salience)
            text, rec = abstract_trait(trait, dna, space, abstraction_floor)
            log.append(rec)
            if text:
                p = _make(dna, trait, text, dim, space, ont, role_eligibility,
                          [dna.identity.reference_id], [trait.trait_id], trait.salience)
                if p:
                    out.append(p)
            continue

        # two or more references speak to this dimension
        ranked = sorted(entries, key=lambda e: (-e[1].salience, e[1].trait_id))
        (dna_a, ta), (dna_b, tb) = ranked[0], ranked[1]
        edge = _edge_between(ont, ta.suggests, tb.suggests) if (ta.suggests and tb.suggests) else "none"
        overlap = bool(set(ta.suggests) & set(tb.suggests))

        if overlap:
            relation = SynthesisRelation.REINFORCE
        elif edge == "tensions_with":
            relation = SynthesisRelation.TENSION_HOLD
        elif edge == "excludes":
            relation = SynthesisRelation.DROP
        elif abs(ta.abstraction - tb.abstraction) >= 0.08:
            relation = SynthesisRelation.SUBSUME
        else:
            relation = SynthesisRelation.BRIDGE

        decisions.append(TraitConflict(
            dimension=dim, trait_a=ta.trait_id, trait_b=tb.trait_id,
            reference_a=dna_a.identity.reference_id, reference_b=dna_b.identity.reference_id,
            relation=relation, edge=edge,
            detail={
                SynthesisRelation.REINFORCE: "both point at the same values; salience raised",
                SynthesisRelation.BRIDGE: "different readings joined into one statement",
                SynthesisRelation.TENSION_HOLD: "kept in tension; the phenotype must reconcile it",
                SynthesisRelation.SUBSUME: "the more abstract statement absorbs the other",
                SynthesisRelation.DROP: "an `excludes` edge; the lower-salience trait is dropped",
            }[relation]))

        text_a, rec_a = abstract_trait(ta, dna_a, space, abstraction_floor)
        log.append(rec_a)
        if text_a is None:
            continue
        text_b, rec_b = abstract_trait(tb, dna_b, space, abstraction_floor)
        log.append(rec_b)

        if relation is SynthesisRelation.DROP or text_b is None:
            statement, refs, traits = text_a, [dna_a.identity.reference_id], [ta.trait_id]
            salience = ta.salience
        elif relation is SynthesisRelation.SUBSUME:
            keep_a = ta.abstraction >= tb.abstraction
            statement = text_a if keep_a else text_b
            refs = [(dna_a if keep_a else dna_b).identity.reference_id]
            traits = [(ta if keep_a else tb).trait_id]
            salience = max(ta.salience, tb.salience)
        else:
            statement = _merge_statements(text_a, text_b, relation)
            refs = [dna_a.identity.reference_id, dna_b.identity.reference_id]
            traits = [ta.trait_id, tb.trait_id]
            salience = min(1.0, max(ta.salience, tb.salience) *
                           (1.15 if relation is SynthesisRelation.REINFORCE else 1.0))

        p = _make(dna_a, ta, statement, dim, space, ont, role_eligibility, refs, traits, salience,
                  synthesised=len(refs) > 1,
                  requires_reconciliation=relation is SynthesisRelation.TENSION_HOLD,
                  extra_suggests=tb.suggests if relation in (
                      SynthesisRelation.BRIDGE, SynthesisRelation.TENSION_HOLD,
                      SynthesisRelation.REINFORCE) else [],
                  blocked_extra=dna_b.surface_lexicon.blocked())
        if p:
            out.append(p)

    out.sort(key=lambda p: (-p.salience, p.id))
    return out[:max_principles], log, decisions


def _make(dna, trait, statement, dim, space, ont, role_eligibility, refs, traits, salience,
          *, synthesised: bool = False, requires_reconciliation: bool = False,
          extra_suggests: list[str] | None = None, blocked_extra: list[str] | None = None):
    facets = map_facets(trait, space)
    if not facets:
        return None
    suggests = list(trait.suggests) + list(extra_suggests or [])
    biases = build_biases(suggests, dim, space)
    facets = sorted(set(facets) | set(biases))
    blocked = sorted(set(dna.surface_lexicon.blocked()) | set(blocked_extra or []))
    pid = RUNTIME_PREFIX + deterministic_id("", *refs, *traits).lstrip("_")
    return Principle(
        id=pid,
        # R-REF-12: a NEW abstract label, never a concatenation of reference names
        source_domain=_abstract_label(dim, statement),
        domain_class=_domain_class_for(dna),
        statements=[statement],
        mappable_to=facets,
        biases=biases,
        forbidden_surface_tokens=blocked,
        provenance=PrincipleProvenance(
            source="SYNTHESIS" if synthesised else "REFERENCE",
            reference_ids=tuple(refs), derived_from_traits=tuple(traits),
            abstraction=trait.abstraction, dimension=dim.value),
        role_eligibility=role_eligibility,
        requires_reconciliation=requires_reconciliation,
        salience=round(salience, 4),
    )
