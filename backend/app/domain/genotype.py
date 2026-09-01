"""The genotype: the machine-searchable half of a concept.

This is what the allocator, the distance metric, the mutation operators and the
repair engine all operate on. It is *solved*, never written by a language model.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from app.domain.common import ACTIVE_FACETS, FacetId, Frozen, MaterialRole, OntologyRef, Score


class FacetAssignment(Frozen):
    value: OntologyRef
    strength: Score = 1.0


class NumericParam(Frozen):
    name: str
    value: float
    unit: str = ""


class GeometrySpec(Frozen):
    system: OntologyRef
    params: list[NumericParam] = []


class MaterialAssignment(Frozen):
    material: OntologyRef
    role: MaterialRole
    share: Score


class CulturalReference(Frozen):
    ref: OntologyRef
    abstraction: Score = 0.7   # 0 = literal quotation ... 1 = principle only
    attribution: str = "REGIONAL_TYPOLOGY"


class ConceptGenotype(Frozen):
    # ---- ACTIVE (12): allocator + distance metric operate on exactly these ----
    thesis_archetype: FacetAssignment
    architectural_language: FacetAssignment
    geometry: GeometrySpec
    structural_logic: FacetAssignment
    material_palette: list[MaterialAssignment] = Field(min_length=2, max_length=5)
    spatial_narrative: list[OntologyRef] = Field(min_length=1, max_length=3)
    occupation_staging: FacetAssignment
    lighting_philosophy: FacetAssignment
    site_relationship: FacetAssignment
    tectonic_logic: FacetAssignment
    scale_strategy: FacetAssignment
    emotional_register: FacetAssignment

    # ---- PASSIVE (6): typed and carried; weight 0.0 in metric v1 ----
    design_philosophy: FacetAssignment | None = None
    ephemerality: FacetAssignment | None = None
    sensory_strategy: list[OntologyRef] = []
    cultural_lineage: list[CulturalReference] = []   # derived from ontology edges
    technology: list[OntologyRef] = []               # derived from requires-closure
    anti_attributes: list[OntologyRef] = []          # computed from the niche

    @model_validator(mode="after")
    def _check_materials(self) -> "ConceptGenotype":
        primaries = [m for m in self.material_palette if m.role == MaterialRole.PRIMARY]
        if len(primaries) != 1:
            raise ValueError("material_palette must contain exactly one PRIMARY")
        if sum(m.share for m in self.material_palette) > 1.0001:
            raise ValueError("material shares must sum to <= 1.0")
        return self

    # -- accessors used by the metric, allocator and prompt compiler --

    def primary_material(self) -> MaterialAssignment:
        return next(m for m in self.material_palette if m.role == MaterialRole.PRIMARY)

    def facet_value(self, facet: FacetId) -> str | None:
        if facet == "geometry_system":
            return self.geometry.system
        if facet in ("material_palette", "spatial_narrative"):
            return None
        fa = getattr(self, facet, None)
        return fa.value if isinstance(fa, FacetAssignment) else None

    def all_refs(self) -> list[str]:
        refs = [self.facet_value(f) for f in ACTIVE_FACETS if self.facet_value(f)]
        refs += [m.material for m in self.material_palette]
        refs += list(self.spatial_narrative)
        return [r for r in refs if r]

    def as_display_rows(self) -> list[tuple[str, str]]:
        """Human-readable DNA rows for the UI."""
        return [
            ("thesis_archetype", self.thesis_archetype.value),
            ("architectural_language", self.architectural_language.value),
            ("geometry_system", self.geometry.system),
            ("structural_logic", self.structural_logic.value),
            ("material_palette", ", ".join(f"{m.material}({m.role.value.lower()})" for m in self.material_palette)),
            ("spatial_narrative", " → ".join(self.spatial_narrative)),
            ("occupation_staging", self.occupation_staging.value),
            ("lighting_philosophy", self.lighting_philosophy.value),
            ("site_relationship", self.site_relationship.value),
            ("tectonic_logic", self.tectonic_logic.value),
            ("scale_strategy", self.scale_strategy.value),
            ("emotional_register", self.emotional_register.value),
        ]


class PartialGenotype(Frozen):
    """A niche skeleton: the facets the allocator fixed, before solving."""
    thesis_archetype: str | None = None
    architectural_language: str | None = None
    geometry_system: str | None = None
    structural_logic: str | None = None
    material_primary: str | None = None
    spatial_narrative: list[str] = []
    occupation_staging: str | None = None
    lighting_philosophy: str | None = None
    site_relationship: str | None = None
    tectonic_logic: str | None = None
    scale_strategy: str | None = None
    emotional_register: str | None = None

    def assigned(self) -> dict[str, str | list[str]]:
        out: dict[str, str | list[str]] = {}
        for f in (
            "thesis_archetype", "architectural_language", "geometry_system", "structural_logic",
            "material_primary", "occupation_staging", "lighting_philosophy", "site_relationship",
            "tectonic_logic", "scale_strategy", "emotional_register",
        ):
            v = getattr(self, f)
            if v:
                out[f] = v
        if self.spatial_narrative:
            out["spatial_narrative"] = list(self.spatial_narrative)
        return out
