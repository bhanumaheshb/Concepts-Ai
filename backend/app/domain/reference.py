"""Reference Intelligence domain models.

Every contract the module produces or consumes. Imports nothing from the application
except `app.core` and `app.domain`, so it stays at the bottom of the dependency stack
alongside the rest of the domain layer.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.versions import VersionStamp
from app.domain.antibrief import ClicheCluster
from app.domain.common import FacetId, Frozen, NicheRole, OntologyRef, Score


# ─────────────────────────── enums ───────────────────────────

class ReferenceType(StrEnum):
    MOVIE = "MOVIE"
    TV_SERIES = "TV_SERIES"
    GAME = "GAME"
    ARCHITECTURE = "ARCHITECTURE"
    ART = "ART"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    HISTORICAL_PERIOD = "HISTORICAL_PERIOD"
    CULTURAL_REFERENCE = "CULTURAL_REFERENCE"
    FASHION = "FASHION"
    NATURE = "NATURE"
    TECHNOLOGY = "TECHNOLOGY"
    OTHER = "OTHER"


class ReferenceDimension(StrEnum):
    # SPATIAL — these map onto genotype facets
    SPATIAL_LANGUAGE = "SPATIAL_LANGUAGE"
    ARCHITECTURAL_LANGUAGE = "ARCHITECTURAL_LANGUAGE"
    GEOMETRY = "GEOMETRY"
    SCALE = "SCALE"
    CIRCULATION_MOVEMENT = "CIRCULATION_MOVEMENT"
    ENVIRONMENTAL_RELATIONSHIP = "ENVIRONMENTAL_RELATIONSHIP"
    # MATERIAL
    MATERIAL_BEHAVIOUR = "MATERIAL_BEHAVIOUR"
    TEXTURE = "TEXTURE"
    COLOUR_BEHAVIOUR = "COLOUR_BEHAVIOUR"
    LIGHTING_PHILOSOPHY = "LIGHTING_PHILOSOPHY"
    # EXPERIENTIAL
    ATMOSPHERE = "ATMOSPHERE"
    EMOTIONAL_TONE = "EMOTIONAL_TONE"
    SENSORY_ASSOCIATION = "SENSORY_ASSOCIATION"
    RHYTHM_PACING = "RHYTHM_PACING"
    # NARRATIVE
    NARRATIVE_STRUCTURE = "NARRATIVE_STRUCTURE"
    SOCIAL_BEHAVIOUR = "SOCIAL_BEHAVIOUR"
    RECURRING_MOTIF = "RECURRING_MOTIF"
    # CONTEXT — inform the phenotype, never bias a facet directly
    ERA = "ERA"
    CULTURAL_CONTEXT = "CULTURAL_CONTEXT"
    TECHNOLOGICAL_CHARACTER = "TECHNOLOGICAL_CHARACTER"


CONTEXT_DIMENSIONS: frozenset[ReferenceDimension] = frozenset({
    ReferenceDimension.ERA,
    ReferenceDimension.CULTURAL_CONTEXT,
    ReferenceDimension.TECHNOLOGICAL_CHARACTER,
})


class ReferencePreset(StrEnum):
    INSPIRED_BY = "INSPIRED_BY"
    ERA = "ERA"
    ATMOSPHERE = "ATMOSPHERE"
    ARCHITECTURAL = "ARCHITECTURAL"
    NARRATIVE = "NARRATIVE"
    HYBRID = "HYBRID"
    FREE_INTERPRETATION = "FREE_INTERPRETATION"


class CompatibilityClass(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    INTERESTING_TENSION = "INTERESTING_TENSION"
    HIGH_RISK = "HIGH_RISK"
    INCOHERENT = "INCOHERENT"


class SynthesisRelation(StrEnum):
    REINFORCE = "REINFORCE"
    BRIDGE = "BRIDGE"
    TENSION_HOLD = "TENSION_HOLD"
    SUBSUME = "SUBSUME"
    DROP = "DROP"


SurfaceCategory = Literal[
    "TITLE", "PROPER_NOUN", "CHARACTER", "PLACE", "FRANCHISE_TERM",
    "ICONIC_OBJECT", "COSTUME", "LOGO", "SET_ELEMENT",
]


# ───────────────────── proper-noun detection ─────────────────────
# Deterministic and conservative: a capitalised token that is not sentence-initial and
# not an ordinary capitalised word. Used by R-REF-06 / R-REF-08 validation.

_ALLOWED_CAPITALS = {
    "I", "A", "An", "The", "It", "Its", "They", "This", "That", "These", "Those",
    "Where", "When", "What", "Which", "While", "Every", "Each", "One", "Two", "Three",
    "Light", "Space", "Form", "Material", "Movement", "Scale", "Colour", "Color",
}
_WORD = re.compile(r"\b[A-Z][a-z]{2,}\b")


def detect_proper_nouns(text: str) -> list[str]:
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n", text):
        tokens = sentence.strip().split()
        for i, tok in enumerate(tokens):
            clean = tok.strip('.,;:!?"()')
            if i == 0 or not _WORD.fullmatch(clean):
                continue
            if clean in _ALLOWED_CAPITALS:
                continue
            out.append(clean)
    return sorted(set(out))


def contains_token(text: str, token: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", text, re.I) is not None


# ─────────────────────────── models ───────────────────────────

class ReferenceIdentity(Frozen):
    reference_id: str
    kind: ReferenceType
    display_name: str          # shown in the UI; MUST NEVER enter a prompt (R-REF-07)
    query: str = ""
    resolved_by: Literal["CURATED", "ANALYSER", "USER_UPLOAD", "UNRESOLVED"] = "CURATED"
    confidence: Score = 1.0
    disambiguation: list[str] = []
    blurb: str = ""
    aliases: list[str] = []


class ReferenceTrait(Frozen):
    trait_id: str
    dimension: ReferenceDimension
    statement: str
    abstraction: Score
    salience: Score
    surface_tokens: list[str] = []
    maps_to: list[FacetId] = []
    suggests: list[OntologyRef] = []
    evidence: str = ""

    @model_validator(mode="after")
    def _context_dims_do_not_bias(self) -> "ReferenceTrait":
        if self.dimension in CONTEXT_DIMENSIONS and self.maps_to:
            raise ValueError(
                f"{self.dimension} is a CONTEXT dimension and must have empty maps_to; "
                f"it informs the phenotype but must never bias a facet"
            )
        for tok in self.surface_tokens:
            if contains_token(self.statement, tok):
                raise ValueError(f"trait statement contains its own surface token {tok!r}")
        return self


class LiteralReading(Frozen):
    """What a weak system would produce. Named explicitly so the engine can occupy it
    exactly once and avoid it everywhere else."""
    label: str
    facet_values: list[OntologyRef] = Field(min_length=2)
    surface_tokens: list[str] = []
    prevalence: Score = 0.9
    naive_rendering: str = ""      # the paragraph a weak system would write


class SurfaceToken(Frozen):
    token: str
    category: SurfaceCategory
    transformed_to: str | None = None
    justification: str = ""        # required when transformed_to is None


class SurfaceLexicon(Frozen):
    tokens: list[SurfaceToken] = []

    def blocked(self) -> list[str]:
        return sorted({t.token.lower() for t in self.tokens})

    def transformed(self) -> list[SurfaceToken]:
        return [t for t in self.tokens if t.transformed_to]

    def merged_with(self, other: "SurfaceLexicon") -> "SurfaceLexicon":
        seen = {t.token.lower(): t for t in self.tokens}
        for t in other.tokens:
            seen.setdefault(t.token.lower(), t)
        return SurfaceLexicon(tokens=[seen[k] for k in sorted(seen)])


class DimensionCoverage(Frozen):
    dimension: ReferenceDimension
    trait_count: int
    max_salience: Score
    load_bearing: bool


class ReferenceDNA(Frozen):
    dna_id: str
    identity: ReferenceIdentity
    traits: list[ReferenceTrait] = Field(min_length=6)
    literal_reading: LiteralReading
    surface_lexicon: SurfaceLexicon
    coverage: list[DimensionCoverage] = []
    analysis_notes: str = ""
    analyser: str | None = None            # None => curated fixture
    versions: VersionStamp | None = None

    @model_validator(mode="after")
    def _protect_surface(self) -> "ReferenceDNA":
        """R-REF-06: no display name, no blocked token, no proper noun in a statement."""
        blocked = set(self.surface_lexicon.blocked())
        name = self.identity.display_name
        for t in self.traits:
            if contains_token(t.statement, name):
                raise ValueError(f"trait {t.trait_id} names the reference ({name!r})")
            for tok in blocked:
                if contains_token(t.statement, tok):
                    raise ValueError(f"trait {t.trait_id} contains blocked token {tok!r}")
            nouns = detect_proper_nouns(t.statement)
            if nouns:
                raise ValueError(f"trait {t.trait_id} contains proper noun(s) {nouns}")
        return self

    def traits_for(self, dimension: ReferenceDimension) -> list[ReferenceTrait]:
        return [t for t in self.traits if t.dimension == dimension]

    def mappable_traits(self) -> list[ReferenceTrait]:
        return sorted([t for t in self.traits if t.maps_to],
                      key=lambda t: (-t.salience, t.trait_id))


class ReferenceInfluence(Frozen):
    """`level` is the only user-facing number; everything else is derived (§9)."""
    level: Score = 0.55
    band: str = "balanced"
    max_biased_facets: int = Field(ge=0, le=3)     # R-REF-02: hard ceiling of 3
    max_principles: int = Field(ge=0, le=8)
    prior_multiplier: float = Field(ge=1.0, le=4.0)
    role_coverage: list[NicheRole] = []
    literal_quota: int = Field(ge=0, le=3)
    abstraction_floor: Score = 0.6

    @model_validator(mode="after")
    def _invariants(self) -> "ReferenceInfluence":
        if NicheRole.WILDCARD in self.role_coverage:
            raise ValueError("R-REF-03: WILDCARD must never receive reference influence")
        if self.max_biased_facets > 3:
            raise ValueError("R-REF-02: at most 3 of 12 facets may be biased")
        return self


class TraitConflict(Frozen):
    dimension: ReferenceDimension
    trait_a: str
    trait_b: str
    reference_a: str
    reference_b: str
    relation: SynthesisRelation
    edge: Literal["tensions_with", "excludes", "none"] = "none"
    detail: str = ""


class ReferenceCompatibility(Frozen):
    reference_ids: list[str]
    verdict: CompatibilityClass
    conflicts: list[TraitConflict] = []
    rationale: str = ""
    influence_cap: Score | None = None     # HIGH_RISK caps influence at 0.6


class FacetPrior(Frozen):
    """R-REF-14: only ever RAISES a weight. Never touches FacetDomain.legal."""
    facet_id: FacetId
    value: OntologyRef
    multiplier: float = Field(ge=1.0, le=4.0)
    source_reference_id: str


class ReferenceTraceLink(Frozen):
    reference_id: str
    trait_id: str
    dimension: ReferenceDimension
    principle_id: str
    facet_id: FacetId
    value: OntologyRef | None = None
    stuck: bool = False


class TransformationChannels(Frozen):
    literal_occupancy: Score = 0.0        # O
    displacement: Score = 0.0             # D
    principle_abstraction: Score = 0.0    # A
    naive_overlap: Score = 0.0            # X
    facet_freedom: Score = 0.0            # F


class ReferenceContext(Frozen):
    """Attached to ConceptDNA. Purely additive; None for every non-reference run."""
    reference_ids: list[str] = []
    injected_principle_ids: list[str] = []
    dimensions: list[ReferenceDimension] = []
    influence_measured: Score = 0.0       # I
    transformation: Score = 0.0           # T
    channels: TransformationChannels = TransformationChannels()
    surface_leaks: list[str] = []         # MUST be empty in a delivered concept
    is_literal_slot: bool = False         # canonical: exempt from the T gate (R-REF-10)
    trace: list[ReferenceTraceLink] = []


class ReferenceSelector(Frozen):
    query: str
    kind: ReferenceType | None = None
    reference_id: str | None = None       # set when the UI resolved it already


class ReferenceRequest(Frozen):
    references: list[ReferenceSelector] = Field(min_length=1, max_length=4)
    influence: Score = 0.55
    dimension_filter: list[ReferenceDimension] = []   # empty => all dimensions
    preset: ReferencePreset = ReferencePreset.INSPIRED_BY
    synthesis: bool = True


class AbstractionRecord(Frozen):
    """Before/after for the debug panel — the evidence that abstraction happened."""
    trait_id: str
    dimension: ReferenceDimension
    raw: str
    lifted: str
    steps_applied: list[str] = []
    removed_tokens: list[str] = []


class CreativePrincipleInjection(Frozen):
    """The ONLY object Reference Intelligence hands to the creative engine (R-REF-01)."""
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    injection_id: str
    principles: list = []                  # list[Principle] — the ontology dataclass
    prior_bias: list[FacetPrior] = []
    cliche_clusters: list[ClicheCluster] = []
    surface_lexicon: SurfaceLexicon = SurfaceLexicon()
    influence: ReferenceInfluence
    compatibility: ReferenceCompatibility | None = None
    reference_dnas: list[ReferenceDNA] = []
    abstraction_log: list[AbstractionRecord] = []
    synthesis_log: list[TraitConflict] = []
    niche_assignment: dict[str, list[str]] = {}   # role -> principle ids (R-REF-20)
    ontology_collisions: list[str] = []           # tokens NOT blocked: ontology vocabulary
    versions: VersionStamp | None = None

    def principle_ids(self) -> list[str]:
        return [p.id for p in self.principles]

    def blocked_tokens(self) -> list[str]:
        return self.surface_lexicon.blocked()
