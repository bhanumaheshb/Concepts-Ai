"""Contracts for LLM creative synthesis.

The division of labour this module encodes:

  * the deterministic engine decides WHAT each concept is (the genotype);
  * the model decides HOW that concept is expressed as architecture;
  * the compiler decides what reaches an image model.

Nothing here lets the model choose the design. `ConstraintEnvelope` states, explicitly
and per concept, which values are locked, which are guidance, and which are genuinely
open — and `ConceptValidation` is how a violation is caught rather than absorbed.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.domain.common import Frozen


class ConstraintKind(StrEnum):
    HARD = "HARD"            # may not be altered — capacity, dimensions, locked facets
    SOFT = "SOFT"            # guidance the model may interpret
    CREATIVE = "CREATIVE"    # genuinely open


class LockedFacet(Frozen):
    """One genotype value the synthesis must express and may not replace (§19)."""
    facet: str
    ref: str
    label: str
    description: str = ""


class ConstraintEnvelope(Frozen):
    """What the model is and is not allowed to move, assembled per concept."""
    hard: list[str] = []            # human-readable statements, each checkable
    soft: list[str] = []
    creative: list[str] = []
    locked_facets: list[LockedFacet] = []
    forbidden_tokens: list[str] = []
    capacity: int | None = None
    site_dimensions: str = ""
    max_height_m: float | None = None
    typology: str = ""

    def hard_summary(self) -> str:
        return "; ".join(self.hard)


# ─────────────────────── the structured concept ───────────────────────

class ProgramResolution(Frozen):
    """Program is resolved from the BRIEF, not invented (§6).

    `focal_space` is deliberately generic: a mandap for a sangeeth, a stage for a
    concert, a counter for a restaurant. A field per event type would have forced the
    model to invent a mandap for a retail interior.
    """
    focal_space: str = ""            # mandap / stage / altar / counter / vitrine
    focal_space_label: str = ""      # what this program calls it
    seating: str = ""
    walkway: str = ""
    arrival: str = ""
    circulation: str = ""
    service_access: str = ""         # empty when the brief does not require it
    back_of_house: str = ""
    sightlines: str = ""
    spatial_hierarchy: str = ""
    additional_zones: list[str] = []


class StructureBlock(Frozen):
    structural_system: str = ""
    geometry: str = ""
    mass_and_void: str = ""
    module: str = ""                 # the repeated unit, where there is one
    spans_and_supports: str = ""
    joints_and_assembly: str = ""


class MaterialsBlock(Frozen):
    """Material + behaviour + location + interaction with light (§11)."""
    primary: str = ""
    material_behaviour: str = ""
    surface_treatment: str = ""
    secondary: list[str] = []
    palette_note: str = ""


class LightingBlock(Frozen):
    """Spatially specific: source, temperature, height, distribution, shadow (§12)."""
    lighting_sources: list[str] = []
    colour_temperature: str = ""
    height_and_distribution: str = ""
    shadow_behaviour: str = ""
    interaction_with_materials: str = ""


class CameraRecommendation(Frozen):
    viewpoint: str = ""
    height: str = ""
    lens: str = ""
    orientation: str = ""
    distance: str = ""
    framing: str = ""
    time_of_day: str = ""

    def as_phrase(self) -> str:
        parts = [self.viewpoint, self.height, self.lens, self.distance,
                 self.framing, self.time_of_day]
        return ", ".join(p.strip() for p in parts if p and p.strip())


class SpatialSequenceStep(Frozen):
    step: str                        # ARRIVAL / THRESHOLD / COMPRESSION / …
    description: str = ""


class StructuredArchitecturalConcept(Frozen):
    """What the model must return. Prose alone is not acceptable (§4)."""
    concept_title: str = ""
    concept_thesis: str = ""
    design_story: str = ""
    architectural_language: str = ""
    spatial_organization: str = ""
    arrival_sequence: str = ""
    circulation: str = ""
    spatial_sequence: list[SpatialSequenceStep] = []
    program: ProgramResolution = ProgramResolution()
    structure: StructureBlock = StructureBlock()
    materials: MaterialsBlock = MaterialsBlock()
    lighting: LightingBlock = LightingBlock()
    atmosphere: str = ""
    landscape: str = ""
    human_experience: str = ""
    camera_recommendation: CameraRecommendation = CameraRecommendation()
    construction_character: str = ""
    distinctive_elements: list[str] = []
    anti_cliches: list[str] = []
    rationale: str = ""

    # provenance — filled by the synthesizer, never by the model
    source: str = "mock"             # provider name
    model: str = ""
    attempts: int = 1
    repaired: bool = False
    duration_ms: int = 0


# ─────────────────────── validation ───────────────────────

class ValidationSeverity(StrEnum):
    ERROR = "ERROR"          # must be repaired
    WARNING = "WARNING"      # recorded, does not trigger a retry


class ValidationFinding(Frozen):
    code: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    field: str = ""
    message: str
    evidence: str = ""


class ConceptValidation(Frozen):
    passed: bool = True
    findings: list[ValidationFinding] = []
    attempts: int = 1
    repaired: bool = False

    @property
    def errors(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity is ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity is ValidationSeverity.WARNING]

    def repair_instruction(self) -> str:
        return "\n".join(f"- [{f.code}] {f.field or 'concept'}: {f.message}"
                         for f in self.errors)


# ─────────────────────── the compiled visualization prompt ───────────────────────

class PromptSection(Frozen):
    name: str
    text: str
    source: str = "concept"          # concept | dna | brief | scene | reference | trend

class ArchitecturalVisualizationPrompt(Frozen):
    """The terminal artefact. Sections are ordered and named so a reader can see
    exactly which layer contributed which sentence."""
    prompt_id: str
    concept_id: str
    sections: list[PromptSection] = []
    positive_prompt: str = ""
    negative_prompt: str = ""
    camera: str = ""
    aspect_ratio: str = "3:2"
    compiler_version: str = "2.0.0"
    prompt_hash: str = ""
    inputs_hash: str = ""
    degraded: bool = False
    missing_sections: list[str] = []
    # Per-area views. The hero prompt leaves these at their defaults; a shot-list
    # prompt names its area and carries the signature of the identity sections it
    # shares with its siblings, which is what makes a set render as one venue.
    view_key: str = "hero"
    view_label: str = "Overall"
    shared_signature: str = ""

    def section(self, name: str) -> str:
        for s in self.sections:
            if s.name == name:
                return s.text
        return ""
