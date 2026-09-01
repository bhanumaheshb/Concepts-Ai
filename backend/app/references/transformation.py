"""§6 — the transformation score.

Six channels, all deterministic, none requiring an image or a model's opinion
(R-REF-09). Three reuse code that already exists and is already under test.

Two quantities, not one:
  I (influence)      — did the reference actually reach the concept
  T (transformation) — did the concept escape the reference's literal reading
"""
from __future__ import annotations

import re

from app.core.seeded import SeededRandom
from app.diversity.metric import genotype_distance
from app.domain.common import ACTIVE_FACETS
from app.domain.genotype import ConceptGenotype, PartialGenotype
from app.domain.reference import (
    ReferenceContext, ReferenceDimension, ReferenceDNA, ReferenceTraceLink,
    TransformationChannels, contains_token,
)
from app.genotype.solve import SolveFailed, solve_genotype
from app.ontology.graph import Ontology, Principle

W_OCCUPANCY, W_DISPLACEMENT, W_ABSTRACTION, W_OVERLAP, W_FREEDOM = 0.25, 0.30, 0.20, 0.15, 0.10
T_GATE = 0.55
I_FLOOR = 0.25
PORTFOLIO_T_MEAN = 0.60
PORTFOLIO_I_COUNT = 7

_STOP = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "with", "for", "is",
    "are", "as", "by", "that", "this", "from", "it", "its", "into", "over", "under",
    "all", "one", "two", "each", "every", "their", "there", "which", "while", "where",
    "has", "have", "been", "was", "were", "be", "but", "not", "so", "up", "down",
}

_literal_cache: dict[tuple[str, str], ConceptGenotype] = {}


def literal_genotype(ont: Ontology, dna: ReferenceDNA, space) -> ConceptGenotype | None:
    """The genotype a weak system would produce, solved in THIS search space.
    Cached per (reference, space) — deterministic, so the cache is safe."""
    key = (dna.identity.reference_id, space.space_id)
    if key in _literal_cache:
        return _literal_cache[key]
    fields: dict[str, object] = {}
    for ref in dna.literal_reading.facet_values:
        facet = ref.split(":", 1)[0]
        if facet == "material":
            fields.setdefault("material_primary", ref)
        elif facet == "spatial_narrative":
            fields.setdefault("spatial_narrative", [ref])
        elif facet in PartialGenotype.model_fields:
            fields.setdefault(facet, ref)
    try:
        g = solve_genotype(ont, space, SeededRandom(0, "literal", dna.identity.reference_id),
                           skeleton=PartialGenotype(**fields))
    except SolveFailed:
        return None
    _literal_cache[key] = g
    return g


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOP}


# ─────────────────────── the six channels ───────────────────────

def surface_leaks(dnas: list[ReferenceDNA], *texts: str,
                  blocked: list[str] | None = None) -> list[str]:
    """Channel 1 — a GATE, not a term. Any leak zeroes the score.

    `blocked` MUST be the injection's collision-filtered list. The raw fixture lexicon
    still contains terms that are also the ontology's own vocabulary ("brutalist",
    "mughal"), and blocking those would forbid the engine from naming its own values.
    """
    blob = " ".join(t for t in texts if t)
    candidates = list(blocked) if blocked is not None else [
        tok for dna in dnas for tok in dna.surface_lexicon.blocked()]
    candidates += [d.identity.display_name for d in dnas]
    found: list[str] = []
    for tok in candidates:
        if tok and contains_token(blob, tok) and tok.lower() not in found:
            found.append(tok.lower())
    return sorted(found)


def literal_occupancy(g: ConceptGenotype, dnas: list[ReferenceDNA]) -> float:
    """Channel 2 — how much of the obvious answer this concept is made of."""
    refs = set(g.all_refs())
    scores = []
    for dna in dnas:
        wanted = set(dna.literal_reading.facet_values)
        if wanted:
            scores.append(len(refs & wanted) / len(wanted))
    return max(scores) if scores else 0.0


def displacement(ont: Ontology, g: ConceptGenotype, dnas: list[ReferenceDNA], space) -> float:
    """Channel 3 — reuses the existing, tested distance metric."""
    ds = []
    for dna in dnas:
        lit = literal_genotype(ont, dna, space)
        if lit is not None:
            ds.append(genotype_distance(ont, g, lit))
    return min(ds) if ds else 0.5      # the NEAREST literal reading is the honest one


def principle_abstraction(principles: list[Principle]) -> float:
    """Channel 4 — salience-weighted mean abstraction of the injected principles."""
    if not principles:
        return 0.0
    num = sum(p.provenance.abstraction * p.salience for p in principles)
    den = sum(p.salience for p in principles) or 1.0
    return min(1.0, num / den)


def naive_overlap(thesis: str, dnas: list[ReferenceDNA]) -> float:
    """Channel 5 — paraphrase detection with no embeddings."""
    tw = _content_words(thesis)
    if not tw:
        return 0.0
    worst = 0.0
    for dna in dnas:
        nw = _content_words(dna.literal_reading.naive_rendering)
        if nw:
            worst = max(worst, len(tw & nw) / len(tw))
    return worst


def facet_freedom(trace: list[ReferenceTraceLink]) -> float:
    """Channel 6 — the practical measurement of R-REF-02."""
    stuck = {t.facet_id for t in trace if t.stuck}
    return max(0.0, 1.0 - len(stuck) / len(ACTIVE_FACETS))


# ─────────────────────── the two numbers ───────────────────────

def build_trace(g: ConceptGenotype, principles: list[Principle],
                dnas: list[ReferenceDNA]) -> list[ReferenceTraceLink]:
    by_ref = {d.identity.reference_id: d for d in dnas}
    links: list[ReferenceTraceLink] = []
    for p in principles:
        rid = p.provenance.reference_ids[0] if p.provenance.reference_ids else "unknown"
        tid = p.provenance.derived_from_traits[0] if p.provenance.derived_from_traits else "-"
        dim = ReferenceDimension(p.provenance.dimension) if p.provenance.dimension else None
        for facet, values in sorted(p.biases.items()):
            actual = _facet_values(g, facet)
            hit = next((v for v in values if v in actual), None)
            links.append(ReferenceTraceLink(
                reference_id=rid, trait_id=tid,
                dimension=dim or ReferenceDimension.ATMOSPHERE,
                principle_id=p.id, facet_id=facet,
                value=hit or (values[0] if values else None), stuck=hit is not None,
            ))
    return links


def _facet_values(g: ConceptGenotype, facet: str) -> set[str]:
    if facet == "material_palette":
        return {m.material for m in g.material_palette}
    if facet == "spatial_narrative":
        return set(g.spatial_narrative)
    v = g.facet_value(facet)
    return {v} if v else set()


def influence_measured(trace: list[ReferenceTraceLink], principles: list[Principle]) -> float:
    """I — salience-weighted fraction of injected principles whose bias actually stuck."""
    if not principles:
        return 0.0
    biasing = [p for p in principles if p.biases]
    if not biasing:
        # every injected principle is statement-only: it shapes the phenotype but has
        # no facet to land on, so genotype influence is real but partial
        return 0.5
    stuck_pids = {t.principle_id for t in trace if t.stuck}
    num = sum(p.salience for p in biasing if p.id in stuck_pids)
    den = sum(p.salience for p in biasing) or 1.0
    return min(1.0, num / den)


def score_concept(
    ont: Ontology, g: ConceptGenotype, thesis: str, prompt_text: str,
    principles: list[Principle], dnas: list[ReferenceDNA], space,
    is_literal_slot: bool = False, blocked: list[str] | None = None,
) -> ReferenceContext:
    leaks = surface_leaks(dnas, thesis, prompt_text, blocked=blocked)
    trace = build_trace(g, principles, dnas)

    channels = TransformationChannels(
        literal_occupancy=round(literal_occupancy(g, dnas), 4),
        displacement=round(displacement(ont, g, dnas, space), 4),
        principle_abstraction=round(principle_abstraction(principles), 4),
        naive_overlap=round(naive_overlap(thesis, dnas), 4),
        facet_freedom=round(facet_freedom(trace), 4),
    )
    if leaks:
        t = 0.0                                     # channel 1 is a gate
    else:
        terms = [
            (W_OCCUPANCY, 1.0 - channels.literal_occupancy),
            (W_DISPLACEMENT, channels.displacement),
            (W_OVERLAP, 1.0 - channels.naive_overlap),
            (W_FREEDOM, channels.facet_freedom),
        ]
        # the abstraction channel only applies when a principle was actually injected;
        # otherwise drop it and renormalise, exactly as the distance metric does for a
        # missing facet
        if principles:
            terms.append((W_ABSTRACTION, channels.principle_abstraction))
        total_w = sum(w for w, _ in terms)
        t = sum(w * v for w, v in terms) / total_w

    measured = influence_measured(trace, principles)
    if is_literal_slot:
        # the canonical carries the reference through the cliché seed, not through a
        # principle: measure how much of the literal reading it actually occupies
        measured = max(measured, channels.literal_occupancy)

    return ReferenceContext(
        reference_ids=[d.identity.reference_id for d in dnas],
        injected_principle_ids=[p.id for p in principles],
        dimensions=sorted({ReferenceDimension(p.provenance.dimension)
                           for p in principles if p.provenance.dimension},
                          key=lambda d: d.value),
        influence_measured=round(measured, 4),
        transformation=round(min(1.0, max(0.0, t)), 4),
        channels=channels, surface_leaks=leaks,
        is_literal_slot=is_literal_slot, trace=trace,
    )
