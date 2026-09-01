"""TRD-06 — TrendCandidate → ReferenceDNA.

The only bridge. After this function a discovered signal is indistinguishable from a
curated reference, and every downstream stage — abstraction, injection, compatibility,
synthesis, transformation, the originality critic, the cliché quota, the Divergence
Engine — is code that already exists and is already tested.

`ReferenceType.OTHER` is used deliberately: a trend signal is a cross-domain observation
about the world, not a work of one type, and OTHER is the profile that enforces no
type-specific dimension coverage. The candidate's own `suggested_reference_type` is kept
for display.
"""
from __future__ import annotations

from app.core.ids import deterministic_id
from app.domain.reference import (
    DimensionCoverage, LiteralReading, ReferenceDimension as D, ReferenceDNA,
    ReferenceIdentity, ReferenceTrait, ReferenceType, SurfaceLexicon, SurfaceToken,
    detect_proper_nouns,
)
from app.domain.trend import TrendCandidate, TrendDomain
from app.ontology.graph import Ontology
from app.references.types import profile

MIN_TRAITS = 6
DERIVED_SALIENCE = 0.45          # supplements never out-rank an authored hint

# A relational reading of what each domain characteristically contributes. Used only to
# supplement authored hints up to the schema minimum, never to replace one.
DOMAIN_READING: dict[TrendDomain, tuple[D, str]] = {
    TrendDomain.ARCHITECTURE: (D.SPATIAL_LANGUAGE,
        "the organising move is legible from a single position in the room"),
    TrendDomain.INTERIOR_DESIGN: (D.TEXTURE,
        "the surface within reach carries more information than the surface at distance"),
    TrendDomain.FASHION: (D.RHYTHM_PACING,
        "the silhouette changes as the wearer moves, and the change is the design"),
    TrendDomain.ART: (D.EMOTIONAL_TONE,
        "the work asks for attention before it offers an explanation"),
    TrendDomain.TECHNOLOGY: (D.TECHNOLOGICAL_CHARACTER,
        "the system's operation is made legible while it runs"),
    TrendDomain.EVENT_DESIGN: (D.SOCIAL_BEHAVIOUR,
        "the crowd is composed as deliberately as the room is"),
    TrendDomain.ENTERTAINMENT: (D.NARRATIVE_STRUCTURE,
        "what is withheld does more work than what is shown"),
    TrendDomain.NATURE: (D.ENVIRONMENTAL_RELATIONSHIP,
        "the system is closed: what falls becomes the ground it fell on"),
    TrendDomain.EXHIBITIONS: (D.SPATIAL_LANGUAGE,
        "the room is arranged around one thing rather than divided between many"),
    TrendDomain.STAGE_DESIGN: (D.NARRATIVE_STRUCTURE,
        "the audience is placed before the subject is revealed"),
    TrendDomain.WEDDING_DESIGN: (D.SOCIAL_BEHAVIOUR,
        "the gathering is arranged so that the collective can see itself"),
}
FALLBACK_READING = (D.ATMOSPHERE, "the space is legible at a glance and rewards a second look")


def _facet_trait(ont: Ontology, candidate: TrendCandidate, idx: int) -> ReferenceTrait | None:
    """A supplementary trait derived from the candidate's OWN literal facets, phrased
    as the behaviour of that value rather than as the value itself."""
    for ref in candidate.literal_facets:
        node = ont.nodes.get(ref)
        if not node or not node.desc:
            continue
        facet = ref.split(":", 1)[0]
        dim = {
            "material": D.MATERIAL_BEHAVIOUR, "tectonic_logic": D.MATERIAL_BEHAVIOUR,
            "geometry_system": D.GEOMETRY, "structural_logic": D.GEOMETRY,
            "lighting_philosophy": D.LIGHTING_PHILOSOPHY,
            "site_relationship": D.ENVIRONMENTAL_RELATIONSHIP,
            "occupation_staging": D.SOCIAL_BEHAVIOUR, "spatial_narrative": D.CIRCULATION_MOVEMENT,
            "emotional_register": D.EMOTIONAL_TONE, "scale_strategy": D.SCALE,
        }.get(facet)
        if dim is None:
            continue
        statement = node.desc.strip().rstrip(".").lower()
        if detect_proper_nouns(statement):
            continue
        return ReferenceTrait(
            trait_id=f"{candidate.candidate_id}_d{idx}", dimension=dim,
            statement=statement, abstraction=0.8, salience=DERIVED_SALIENCE,
            maps_to=[], suggests=[],
            evidence="derived from the signal's own material reading",
        )
    return None


def candidate_to_dna(ont: Ontology, candidate: TrendCandidate) -> ReferenceDNA:
    traits: list[ReferenceTrait] = []
    for i, h in enumerate(candidate.principle_hints):
        suggests = [s for s in h.suggests if s in ont.nodes]      # never invent a ref
        traits.append(ReferenceTrait(
            trait_id=f"{candidate.candidate_id}_h{i}", dimension=h.dimension,
            statement=h.statement, abstraction=h.abstraction, salience=h.salience,
            maps_to=[], suggests=suggests,
            evidence=f"authored reading of a {candidate.domain.value.lower()} signal",
        ))

    # supplement up to the schema minimum, from the candidate's own content
    idx = 0
    while len(traits) < MIN_TRAITS:
        idx += 1
        if idx == 1:
            dim, statement = DOMAIN_READING.get(candidate.domain, FALLBACK_READING)
            traits.append(ReferenceTrait(
                trait_id=f"{candidate.candidate_id}_d{idx}", dimension=dim,
                statement=statement, abstraction=0.88, salience=DERIVED_SALIENCE,
                maps_to=[], suggests=[],
                evidence=f"characteristic reading of the {candidate.domain.value.lower()} domain"))
            continue
        if idx == 2 and (t := _facet_trait(ont, candidate, idx)):
            traits.append(t)
            continue
        traits.append(ReferenceTrait(
            trait_id=f"{candidate.candidate_id}_d{idx}", dimension=D.CULTURAL_CONTEXT,
            statement=f"a reading that is {candidate.freshness.value.lower()} rather than settled",
            abstraction=0.82, salience=0.4, maps_to=[], suggests=[],
            evidence=f"freshness classified from {candidate.corroboration} source(s)"))

    # surface protection: proper nouns in the title and any declared brand terms
    tokens: list[SurfaceToken] = [
        SurfaceToken(token=t, category="PROPER_NOUN",
                     justification="a named work or brand from the discovered signal")
        for t in dict.fromkeys(candidate.surface_terms + detect_proper_nouns(candidate.title))
    ]
    lexicon = SurfaceLexicon(tokens=tokens)

    facets = [f for f in candidate.literal_facets if f in ont.nodes]
    if len(facets) < 2:
        facets = (facets + ["geometry_system:orthogonal_grid", "material:lime_plaster"])[:2]
    literal = LiteralReading(
        label=candidate.literal_label or f"a literal rendering of {candidate.title.lower()}",
        facet_values=facets, surface_tokens=list(candidate.surface_terms),
        prevalence=0.85,
        naive_rendering=candidate.naive_rendering or
            f"A direct visual copy of {candidate.title}, reproduced as set dressing "
            f"rather than interpreted as a spatial idea.",
    )

    prof = profile(ReferenceType.OTHER)
    dims = sorted({t.dimension for t in traits}, key=lambda d: d.value)
    return ReferenceDNA(
        dna_id=deterministic_id("rdna", candidate.candidate_id, ont.version),
        identity=ReferenceIdentity(
            reference_id=f"trend_{candidate.candidate_id}",
            kind=ReferenceType.OTHER,          # a cross-domain signal, not a typed work
            display_name=candidate.title, query=candidate.title,
            resolved_by="ANALYSER", confidence=round(candidate.score or 0.7, 3),
            blurb=candidate.summary[:200],
        ),
        traits=traits, literal_reading=literal, surface_lexicon=lexicon,
        coverage=[DimensionCoverage(
            dimension=d, trait_count=len([t for t in traits if t.dimension == d]),
            max_salience=max(t.salience for t in traits if t.dimension == d),
            load_bearing=d in prof.load_bearing) for d in dims],
        analysis_notes=f"discovered signal · {candidate.domain.value} · "
                       f"{candidate.freshness.value}"
                       + (" · MOCK TREND DATA" if candidate.is_mock else ""),
        analyser="trend:mock" if candidate.is_mock else "trend:live",
    )
