"""§8 — compatibility, classified by the ontology's own typed edges.

No new knowledge base: `tensions_with` is the ontology stating a pairing is valid but
owes an argument; `excludes` is physics or culture. That distinction is exactly the
difference between INTERESTING_TENSION and INCOHERENT.
"""
from __future__ import annotations

from app.domain.reference import (
    CompatibilityClass, ReferenceCompatibility, ReferenceDNA, SynthesisRelation, TraitConflict,
)
from app.ontology.graph import Ontology
from app.references.types import facets_for

HEAVY_FACET_WEIGHT = 0.10
HIGH_RISK_CAP = 0.6


def _heavy(ont: Ontology, dimension) -> bool:
    return any(ont.weight(f) >= HEAVY_FACET_WEIGHT for f in facets_for(dimension))


def _edge_between(ont: Ontology, a_suggests: list[str], b_suggests: list[str]) -> str:
    for a in a_suggests:
        ex = ont.excludes(a)
        for b in b_suggests:
            if b in ex:
                return "excludes"
    tension_targets = {t for a in a_suggests for t, _ in ont.tensions(a)}
    if tension_targets & set(b_suggests):
        return "tensions_with"
    return "none"


def _tension_pair(ont: Ontology, a_vals: list[str], b_vals: list[str]) -> tuple[str, str]:
    for a in a_vals:
        targets = {t for t, _ in ont.tensions(a)}
        for b in b_vals:
            if b in targets:
                return a, b
    return (a_vals[0] if a_vals else ""), (b_vals[0] if b_vals else "")


def _dim_of(dna: ReferenceDNA, value: str):
    for t in dna.traits:
        if value in t.suggests:
            return t.dimension
    return None


def _trait_of(dna: ReferenceDNA, value: str) -> str:
    for t in dna.traits:
        if value in t.suggests:
            return t.trait_id
    return "-"


def classify(ont: Ontology, dnas: list[ReferenceDNA]) -> ReferenceCompatibility:
    ids = [d.identity.reference_id for d in dnas]
    if len(dnas) < 2:
        return ReferenceCompatibility(reference_ids=ids, verdict=CompatibilityClass.COMPATIBLE,
                                      rationale="single reference")

    conflicts: list[TraitConflict] = []

    # 1 — within-dimension: where two references speak to the same thing
    for i, a in enumerate(dnas):
        for b in dnas[i + 1:]:
            shared = {t.dimension for t in a.traits} & {t.dimension for t in b.traits}
            for dim in sorted(shared, key=lambda d: d.value):
                ta = max(a.traits_for(dim), key=lambda t: t.salience)
                tb = max(b.traits_for(dim), key=lambda t: t.salience)
                if not ta.suggests or not tb.suggests:
                    continue
                if set(ta.suggests) & set(tb.suggests):
                    conflicts.append(TraitConflict(
                        dimension=dim, trait_a=ta.trait_id, trait_b=tb.trait_id,
                        reference_a=a.identity.reference_id, reference_b=b.identity.reference_id,
                        relation=SynthesisRelation.REINFORCE, edge="none",
                        detail="both references point at the same ontology values"))
                    continue
                edge = _edge_between(ont, ta.suggests, tb.suggests)
                relation = {
                    "excludes": SynthesisRelation.DROP,
                    "tensions_with": SynthesisRelation.TENSION_HOLD,
                    "none": SynthesisRelation.SUBSUME,
                }[edge]
                conflicts.append(TraitConflict(
                    dimension=dim, trait_a=ta.trait_id, trait_b=tb.trait_id,
                    reference_a=a.identity.reference_id, reference_b=b.identity.reference_id,
                    relation=relation, edge=edge,
                    detail=f"{ta.suggests[:2]} vs {tb.suggests[:2]}"))

    # 2 — cross-dimension: ontology tension edges are between VALUES, not dimensions.
    # "declared mass" vs "tenderness" spans ARCHITECTURAL_LANGUAGE and EMOTIONAL_TONE;
    # a within-dimension scan alone would miss every real licensed tension.
    for i, a in enumerate(dnas):
        for b in dnas[i + 1:]:
            a_vals = sorted({s for t in a.traits for s in t.suggests})
            b_vals = sorted({s for t in b.traits for s in t.suggests})
            if _edge_between(ont, a_vals, b_vals) != "tensions_with":
                continue
            va, vb = _tension_pair(ont, a_vals, b_vals)
            dim = _dim_of(a, va) or _dim_of(b, vb)
            if dim is None:
                continue
            conflicts.append(TraitConflict(
                dimension=dim, trait_a=_trait_of(a, va), trait_b=_trait_of(b, vb),
                reference_a=a.identity.reference_id, reference_b=b.identity.reference_id,
                relation=SynthesisRelation.TENSION_HOLD, edge="tensions_with",
                detail=f"cross-dimension: {va} tensions with {vb}"))

    real = [c for c in conflicts if c.relation is not SynthesisRelation.REINFORCE]
    heavy = [c for c in real if _heavy(ont, c.dimension) and c.edge == "none"]
    excluded = [c for c in real if c.edge == "excludes"]
    tensioned = [c for c in real if c.edge == "tensions_with"]

    if tensioned:
        # a licensed tension is the GOOD case and takes priority: an `excludes` pair is
        # resolved by dropping one trait, it does not condemn the combination
        verdict = CompatibilityClass.INTERESTING_TENSION
        rationale = ("the ontology licenses this pairing as a tension: valid, but the concept "
                     "owes a reconciliation — routed deliberately to RADICAL and EXPLORATORY")
        cap = None
    elif len(excluded) >= 3 and len(excluded) >= 0.6 * max(1, len(real)):
        verdict = CompatibilityClass.INCOHERENT
        rationale = ("most shared dimensions are separated by `excludes` edges; the lower-salience "
                     "trait is dropped in each and the combination continues (R-REF-13)")
        cap = HIGH_RISK_CAP
    elif len(heavy) >= 2:
        verdict = CompatibilityClass.HIGH_RISK
        rationale = (f"{len(heavy)} unlicensed conflicts on high-weight dimensions; accepted with "
                     f"influence capped at {HIGH_RISK_CAP} so the engine has room to resolve them")
        cap = HIGH_RISK_CAP
    else:
        verdict = CompatibilityClass.COMPATIBLE
        rationale = "no conflicts on any high-weight dimension"
        cap = None

    return ReferenceCompatibility(reference_ids=ids, verdict=verdict, conflicts=conflicts,
                                  rationale=rationale, influence_cap=cap)
