"""Primitive types and enums shared by every contract.

This package imports nothing else from the application — it is the bottom of the
dependency stack (spec §20), which is what lets provider protocols live here.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# "facet:value" e.g. "geometry_system:radial_concentric"
OntologyRef = Annotated[str, StringConstraints(pattern=r"^[a-z_]+:[a-z0-9_]+$")]
FacetId = Annotated[str, StringConstraints(pattern=r"^[a-z_]+$")]
ConstraintId = Annotated[str, StringConstraints(pattern=r"^c_[a-z0-9_]+$")]
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class Frozen(BaseModel):
    """Base for every domain contract: strict, immutable, no free-form dicts."""
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelTier(StrEnum):
    CHEAP = "CHEAP"
    EXTRACTION = "EXTRACTION"
    CRITIQUE = "CRITIQUE"
    SYNTHESIS = "SYNTHESIS"


class NicheRole(StrEnum):
    CANONICAL = "CANONICAL"
    ADJACENT = "ADJACENT"
    EXPLORATORY = "EXPLORATORY"
    RADICAL = "RADICAL"
    WILDCARD = "WILDCARD"


class Typology(StrEnum):
    WEDDING_MANDAP = "WEDDING_MANDAP"
    EVENT_STAGE = "EVENT_STAGE"
    RESTAURANT = "RESTAURANT"
    INTERIOR = "INTERIOR"
    PAVILION = "PAVILION"
    EXHIBITION = "EXHIBITION"
    GENERIC_SPATIAL = "GENERIC_SPATIAL"


class CriticName(StrEnum):
    ALIGNMENT = "ALIGNMENT"
    COHERENCE = "COHERENCE"
    FEASIBILITY = "FEASIBILITY"
    CULTURAL = "CULTURAL"
    ORIGINALITY = "ORIGINALITY"      # runs only when a reference is present


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class MaterialRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    ACCENT = "ACCENT"
    FIGURE = "FIGURE"


class ViewRole(StrEnum):
    HERO = "HERO"
    ARRIVAL = "ARRIVAL"
    OCCUPIED = "OCCUPIED"
    DETAIL = "DETAIL"
    NIGHT = "NIGHT"


# The twelve facets the allocator and the distance metric operate on.
ACTIVE_FACETS: tuple[str, ...] = (
    "thesis_archetype",
    "architectural_language",
    "geometry_system",
    "structural_logic",
    "material_palette",
    "spatial_narrative",
    "occupation_staging",
    "lighting_philosophy",
    "site_relationship",
    "tectonic_logic",
    "scale_strategy",
    "emotional_register",
)

# Facets that define a concept's identity. Mutation and repair may never touch these.
IDENTITY_FACETS: frozenset[str] = frozenset(
    {"thesis_archetype", "spatial_narrative", "emotional_register"}
)
