"""The engine's terminal artefact.

PromptCompilation is a deliverable in its own right, not a string on its way to an
image model — which is why it carries segment provenance, a hash and version stamps.
"""
from __future__ import annotations

from typing import Literal

from app.domain.common import Frozen, ViewRole

SegmentKind = Literal[
    "SUBJECT", "LANGUAGE", "FORM", "SCALE", "STRUCTURE", "MATERIAL", "STAGING",
    "OCCUPANCY", "LIGHTING", "ATMOSPHERE", "CAMERA", "CONTEXT", "REGISTER",
]


class PromptSegment(Frozen):
    order: int
    kind: SegmentKind
    text: str
    sources: list[str] = []     # "genotype.material_palette[0]", "scene.court.radius_m"


class PromptCompilation(Frozen):
    prompt_id: str
    concept_id: str
    scene_graph_id: str | None = None
    view_role: ViewRole = ViewRole.HERO
    dialect: Literal["GENERIC", "FLUX", "IMAGEN", "SDXL"] = "GENERIC"
    positive_prompt: str
    negative_prompt: str
    segments: list[PromptSegment] = []
    aspect_ratio: str = "3:2"
    seed: int = 0
    degraded: bool = False
    lint_warnings: list[str] = []
    compiler_version: str = "1.0.0"
    ontology_version: str = "v1"
    inputs_hash: str = ""
    prompt_hash: str = ""
