"""What the user is actually asking for.

Everything the creative engine used to infer from a typology enum is represented
here explicitly, with a source for every decision. The shape is deliberately
domain-general: a Sangeet, a Haldi, a product launch, a restaurant and an event no
one has coded for are all the same object with different contents.

Identity is free text resolved against a knowledge base, never a closed enum. An
event type the knowledge base has never seen is valid: it keeps its own name and
its programme is inferred from what happens in it.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.domain.common import Frozen, Score

# lower_snake identifiers: "sangeet", "dance_floor", "ritual_fire"
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$", max_length=64)]


class Provenance(StrEnum):
    """Where a decision came from. The answer to "why did the system add a mandap?"."""
    USER_EXPLICIT = "USER_EXPLICIT"             # the brief text or a UI selection said so
    SEMANTIC_INFERENCE = "SEMANTIC_INFERENCE"   # derived from other resolved semantics
    DOMAIN_KNOWLEDGE = "DOMAIN_KNOWLEDGE"       # the knowledge base, for a known type
    CREATIVE_OPERATOR = "CREATIVE_OPERATOR"     # a cognition / mutation operator
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"   # a code rule (scale, universals, scope)
    LLM_INFERENCE = "LLM_INFERENCE"             # the reasoning model proposed it
    REPAIR = "REPAIR"                           # introduced while fixing a finding


class ElementStatus(StrEnum):
    REQUIRED = "REQUIRED"
    RECOMMENDED = "RECOMMENDED"
    OPTIONAL = "OPTIONAL"
    FORBIDDEN = "FORBIDDEN"
    CONTEXTUAL = "CONTEXTUAL"       # may inform language or detail, never a programme zone


# How the people present relate to what they came for. Small and stable on purpose:
# it drives staging priors and camera choice, so every value must mean something
# spatially. Anything finer belongs in `focal_relationship` prose.
AudienceRelationship = Literal[
    "frontal",        # one direction of attention: stage, runway end, keynote
    "surround",       # attention converges from several sides: in the round, thrust
    "immersive",      # the audience is inside the medium: projection, installation
    "distributed",    # many simultaneous foci: exhibition, festival, market
    "participatory",  # the audience is the event: dance floor, Haldi, workshop
    "processional",   # attention moves along a route: procession, runway walk
    "convivial",      # attention is on each other: dining, lounge, cocktail
    "none",
]

ZoneRole = Literal[
    "arrival", "focal", "performance", "audience", "participation", "social",
    "hospitality", "dining", "display", "ceremony", "circulation", "service",
    "technical", "backstage", "media", "support", "outdoor", "retail", "work",
]


class Sourced(Frozen):
    """A resolved value plus why it is there."""
    provenance: Provenance
    confidence: Score = 1.0
    rationale: str = ""


class SemanticItem(Sourced):
    key: Slug
    label: str


class SemanticElement(Sourced):
    """A physical or programmatic thing that may or may not belong in the concept."""
    key: Slug
    label: str
    status: ElementStatus
    # the rule that decided the status, when a rule did (scope, user override, …)
    rule: str = ""


class ProgramZone(Sourced):
    key: Slug
    label: str
    role: ZoneRole
    priority: Literal["required", "recommended", "optional"] = "required"
    area_share: float = Field(default=0.1, ge=0.0, le=1.0)
    capacity_share: float = Field(default=0.0, ge=0.0, le=1.0)
    adjacent_to: list[Slug] = []
    activity: Slug | None = None          # the activity that implied this zone


class EventIdentity(Frozen):
    domain: Slug = "event"                 # event | interior | architecture | installation | landscape
    event_family: Slug | None = None       # wedding_celebration, live_entertainment, corporate …
    event_type: Slug = "unspecified"       # sangeet, haldi, product_launch — or an unknown slug
    event_type_label: str = "Unspecified"
    subtype: str | None = None
    tradition: Slug | None = None          # hindu, muslim, christian, sikh, secular
    culture: str | None = None             # regional / cultural context in words
    venue_type: Slug | None = None
    known_type: bool = False               # resolved against the knowledge base?
    proper_name: bool = False              # a name (Sangeet, Nikah) rather than a common noun
    provenance: Provenance = Provenance.DETERMINISTIC_RULE
    confidence: Score = 0.5


def display_label(identity: "EventIdentity") -> str:
    """The event as it reads inside a sentence: 'a Sangeet', 'a product launch'."""
    label = identity.event_type_label or "event"
    return label if identity.proper_name else label[:1].lower() + label[1:]


class EventProfile(Frozen):
    """The event, described by what happens in it rather than what it is called."""
    identity: EventIdentity = EventIdentity()
    primary_activities: list[SemanticItem] = []
    secondary_activities: list[SemanticItem] = []
    participants: list[str] = []
    audience_relationship: AudienceRelationship = "none"
    focal_relationship: str = ""
    atmosphere: list[str] = []
    operational_needs: list[str] = []
    cultural_context: list[str] = []
    elements: list[SemanticElement] = []
    # conceptual pairs a creative operator may act on, e.g. "performer|audience"
    relationships: list[str] = []
    recognisability_cues: list[str] = []

    # -- element views ------------------------------------------------------
    def with_status(self, status: ElementStatus) -> list[SemanticElement]:
        return [e for e in self.elements if e.status == status]

    def forbidden_keys(self) -> set[str]:
        return {e.key for e in self.elements if e.status == ElementStatus.FORBIDDEN}

    def allowed_keys(self) -> set[str]:
        return {e.key for e in self.elements if e.status != ElementStatus.FORBIDDEN}

    def element(self, key: str) -> SemanticElement | None:
        return next((e for e in self.elements if e.key == key), None)


class DesignIntent(Frozen):
    """What the design must achieve, before any form is chosen."""
    primary_activity: str = ""
    primary_focus: str = ""
    primary_zone_key: str = ""
    experience_goals: list[str] = []
    visual_priorities: list[str] = []
    must_communicate: list[str] = []      # what makes an image read as THIS event
    avoid: list[str] = []
    uncertainties: list[str] = []


class ReasonerTrace(Frozen):
    """How the semantic reading was produced. A deterministic reading says so."""
    source: Literal["LLM", "DETERMINISTIC", "MERGED"] = "DETERMINISTIC"
    model: str = ""
    latency_ms: int = 0
    attempts: int = 0
    error: str | None = None
    overridden: list[str] = []           # LLM proposals rejected by an invariant, and why


class SemanticBrief(Frozen):
    raw_text: str
    profile: EventProfile = EventProfile()
    intent: DesignIntent = DesignIntent()
    programme: list[ProgramZone] = []
    capacity: int | None = None
    location: str | None = None
    hard_constraints: list[str] = []
    soft_constraints: list[str] = []
    explicit_requests: list[Slug] = []   # elements the user named — these override defaults
    invariants: list[SemanticInvariant] = []
    ritual_refs: list[str] = []          # ontology refs a rite makes sacred
    space_typology: str = "GENERIC_SPATIAL"   # legacy space-form prior for ontology affinities
    reasoner: ReasonerTrace = ReasonerTrace()

    def zone(self, key: str) -> ProgramZone | None:
        return next((z for z in self.programme if z.key == key), None)

    def primary_zone(self) -> ProgramZone | None:
        """The zone the concept is organised around, as Design Intelligence decided."""
        return self.zone(self.intent.primary_zone_key) if self.intent.primary_zone_key else None


class SemanticInvariant(Sourced):
    """A hard requirement implied by the semantics, e.g. a sightline or a rite."""
    id: Annotated[str, StringConstraints(pattern=r"^c_[a-z0-9_]+$")]
    statement: str
    category: str = "PROGRAM"
    sacred: bool = False           # unreachable by every mutation operator


class LLMCallRecord(Frozen):
    """One model call, as observability needs it. No prompt text, no secrets."""
    stage: str
    purpose: str
    schema_name: str
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    attempts: int = 0
    success: bool = False
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
