from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.common import ConstraintId, FacetId, Frozen, OntologyRef, Score, Typology


class Measurable(Frozen):
    """Presence of this object is what makes a constraint deterministically checkable."""
    field_path: str
    op: Literal["LTE", "GTE", "EQ", "RANGE", "CONTAINS", "EXISTS"]
    value: float | int | str | list[float]
    unit: str | None = None


class Constraint(Frozen):
    constraint_id: ConstraintId
    kind: Literal["HARD", "SOFT"]
    category: Literal[
        "RITUAL", "SAFETY", "CAPACITY", "BUDGET", "SITE", "SCHEDULE", "CLIMATE", "ACCESS", "PROGRAM"
    ]
    statement: str
    measurable: Measurable | None = None
    source: Literal["BRIEF", "INFERRED", "DEFAULT", "TYPOLOGY"] = "BRIEF"
    confidence: Score = 1.0
    sacred: bool = False  # true => unreachable by every mutation operator, forever


class SoftIntent(Frozen):
    intent_id: str
    statement: str
    facet_id: FacetId | None = None
    target_values: list[OntologyRef] = []
    weight: Score = 0.5


class ClimateSpec(Frozen):
    label: Literal["hot_dry", "hot_humid", "temperate", "monsoon", "cold"] = "temperate"
    month: int = 1
    temp_c_p90: float | None = None
    rain_risk: Score = 0.2


class SiteSpec(Frozen):
    kind: Literal["INDOOR", "OUTDOOR", "COVERED", "MIXED"] = "OUTDOOR"
    width_m: float = 30.0
    depth_m: float = 20.0
    height_clear_m: float | None = None
    ground: Literal["LAWN", "HARD", "SAND", "WATER", "FLOOR", "UNKNOWN"] = "LAWN"
    orientation_deg: float = 0.0
    climate: ClimateSpec = ClimateSpec()
    notes: list[str] = []

    @property
    def usable_area_m2(self) -> float:
        return self.width_m * self.depth_m


class BudgetBand(Frozen):
    band: int = Field(ge=1, le=5, default=3)
    currency: str = "INR"
    ceiling_minor: int | None = None


class ScheduleSpec(Frozen):
    load_in_hours: float = 24.0
    strike_hours: float = 8.0
    event_month: int = 1


class CapacitySpec(Frozen):
    guests: int = 100
    seated: int = 100
    principals: int = 2


class RitualProfile(Frozen):
    tradition: str | None = None
    region: str | None = None
    community: str | None = None
    required_elements: list[OntologyRef] = []
    notes: list[str] = []


class RequiredZone(Frozen):
    zone: str
    min_area_m2: float = 0.0
    capacity: int = 0


class Attachment(Frozen):
    attachment_id: str
    kind: Literal["SITE_PHOTO", "REFERENCE_IMAGE", "FLOOR_PLAN", "DOCUMENT"]
    caption: str | None = None


class DesignBrief(Frozen):
    brief_id: str
    project_id: str | None = None
    raw_text: str
    typology: Typology = Typology.GENERIC_SPATIAL
    location: str | None = None
    dimensions_text: str | None = None
    budget_text: str | None = None
    constraints_text: str | None = None
    attachments: list[Attachment] = []
    created_at: str | None = None


class DesignProgram(Frozen):
    """The machine-checkable contract extracted from the brief. Everything downstream
    validates against this object, not against the brief prose."""
    program_id: str
    brief_id: str
    typology: Typology
    invariants: list[Constraint] = []      # all kind == HARD
    soft_intents: list[SoftIntent] = []
    open_variables: list[FacetId] = []
    site: SiteSpec = SiteSpec()
    budget: BudgetBand = BudgetBand()
    schedule: ScheduleSpec = ScheduleSpec()
    capacity: CapacitySpec = CapacitySpec()
    ritual: RitualProfile | None = None
    required_zones: list[RequiredZone] = []
    summary: str = ""

    def constraint_ids(self) -> set[str]:
        return {c.constraint_id for c in self.invariants}

    def sacred_refs(self) -> set[str]:
        out: set[str] = set()
        if self.ritual:
            out |= set(self.ritual.required_elements)
        return out
