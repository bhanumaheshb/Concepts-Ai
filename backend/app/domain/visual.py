"""Visual intent: what an image of a concept must communicate, decided before any prompt.

The Visual Director reasons like an architectural visualisation director — which view
tells this story, where the camera stands, what is in front, who is doing what, what
must be legible — and writes the answer here, in structure. The prompt compiler then
turns structure into words for a particular image model. Reasoning and wording are
separate on purpose: the same intent can later drive video, 3D or CAD generation
without re-deciding what the image is for.
"""
from __future__ import annotations

from typing import Literal

from app.domain.common import Frozen


class VisualIntent(Frozen):
    concept_id: str
    view_key: str                       # "hero", a programme zone key, or a drawing axis
    view_label: str
    zone_key: str | None = None
    render_intent: Literal["photoreal_render", "orthographic_drawing"] = "photoreal_render"

    visual_subject: str
    story_of_image: str = ""

    # camera
    camera_position: str = ""
    camera_height_m: float | None = None
    lens_mm: int | None = None
    field_of_view: str = ""
    view_direction: str = ""
    composition: str = ""

    # depth layers
    foreground: str = ""
    midground: str = ""
    background: str = ""
    depth: str = ""

    # what is seen
    primary_focal_point: str = ""
    secondary_focal_points: list[str] = []
    visible_program_zones: list[str] = []
    important_elements: list[str] = []
    elements_to_avoid: list[str] = []

    # people
    human_activity: str = ""
    occupancy: str = ""
    scale_cues: list[str] = []

    # legibility
    material_readability: str = ""
    structural_readability: str = ""
    lighting: str = ""
    time_of_day: str = ""
    atmosphere: list[str] = []
    annotation_requirements: list[str] = []

    # which source decided each field: semantic | concept | genotype | scene | template | llm
    provenance: dict[str, str] = {}
    overridden: list[str] = []          # proposals dropped by an invariant, with the reason

    def camera_phrase(self) -> str:
        bits = [self.camera_position]
        if self.camera_height_m is not None:
            bits.append(f"camera height {self.camera_height_m:.1f} m")
        if self.lens_mm:
            bits.append(f"{self.lens_mm} mm lens")
        bits += [self.field_of_view, self.view_direction]
        return ", ".join(b for b in bits if b)

    def layers_phrase(self) -> str:
        bits = []
        if self.foreground:
            bits.append(f"foreground: {self.foreground}")
        if self.midground:
            bits.append(f"midground: {self.midground}")
        if self.background:
            bits.append(f"background: {self.background}")
        return "; ".join(bits)
