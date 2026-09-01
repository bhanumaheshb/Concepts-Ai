"""JSON schema for the structured concept, plus tolerant coercion.

A 4B local model will occasionally return a string where the schema asks for a list, or
omit an optional block entirely. Coercion repairs shape without inventing content: an
absent field stays empty and is caught by the validator, never quietly filled in.
"""
from __future__ import annotations

from typing import Any

from app.domain.synthesis import (
    CameraRecommendation, LightingBlock, MaterialsBlock, ProgramResolution,
    SpatialSequenceStep, StructuredArchitecturalConcept, StructureBlock,
)

_STR_FIELDS = ("concept_title", "concept_thesis", "design_story",
               "architectural_language", "spatial_organization", "arrival_sequence",
               "circulation", "atmosphere", "landscape", "human_experience",
               "construction_character", "rationale")
_LIST_FIELDS = ("distinctive_elements", "anti_cliches")


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return "; ".join(_s(x) for x in v if x)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_s(x)}" for k, x in v.items() if x)
    return str(v)


def _ls(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        parts = [p.strip() for p in v.replace(";", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(v, (list, tuple)):
        return [_s(x) for x in v if _s(x)]
    return [_s(v)]


def _sub(raw: Any) -> dict:
    return raw if isinstance(raw, dict) else {}


def concept_json_schema() -> dict:
    """Passed to the serving framework as a grammar constraint where supported."""
    def s(desc: str = "") -> dict:
        return {"type": "string"}

    def arr() -> dict:
        return {"type": "array", "items": {"type": "string"}}

    return {
        "type": "object",
        "properties": {
            "concept_title": s(), "concept_thesis": s(), "design_story": s(),
            "architectural_language": s(), "spatial_organization": s(),
            "arrival_sequence": s(), "circulation": s(),
            # minItems mirrors the validator's own threshold. Where the server
            # honours the schema as a grammar, this is what stops a model from
            # returning an empty list and failing validation for a shape reason.
            "spatial_sequence": {
                "type": "array", "minItems": 3,
                "items": {"type": "object",
                          "properties": {"step": s(), "description": s()},
                          "required": ["step", "description"]}},
            "program": {"type": "object", "properties": {
                "focal_space": s(), "focal_space_label": s(), "seating": s(),
                "walkway": s(), "arrival": s(), "circulation": s(),
                "service_access": s(), "back_of_house": s(), "sightlines": s(),
                "spatial_hierarchy": s(), "additional_zones": arr()},
                "required": ["focal_space", "seating", "walkway", "arrival",
                             "circulation"]},
            "structure": {"type": "object", "properties": {
                "structural_system": s(), "geometry": s(), "mass_and_void": s(),
                "module": s(), "spans_and_supports": s(), "joints_and_assembly": s()},
                "required": ["structural_system", "geometry", "mass_and_void",
                             "module", "spans_and_supports"]},
            "materials": {"type": "object", "properties": {
                "primary": s(), "material_behaviour": s(), "surface_treatment": s(),
                "secondary": arr(), "palette_note": s()},
                "required": ["primary", "material_behaviour", "surface_treatment"]},
            "lighting": {"type": "object", "properties": {
                "lighting_sources": arr(), "colour_temperature": s(),
                "height_and_distribution": s(), "shadow_behaviour": s(),
                "interaction_with_materials": s()},
                "required": ["lighting_sources", "colour_temperature",
                             "height_and_distribution", "shadow_behaviour"]},
            "atmosphere": s(), "landscape": s(), "human_experience": s(),
            "camera_recommendation": {"type": "object", "properties": {
                "viewpoint": s(), "height": s(), "lens": s(), "orientation": s(),
                "distance": s(), "framing": s(), "time_of_day": s()},
                "required": ["viewpoint", "height", "lens", "framing"]},
            "construction_character": s(),
            "distinctive_elements": arr(),
            "anti_cliches": {"type": "array", "minItems": 1,
                             "items": {"type": "string"}},
            "rationale": s(),
        },
        # Everything the validator treats as mandatory must be required HERE too.
        # A field the schema calls optional is a field a well-behaved model will
        # omit — and then fail validation for. `spatial_sequence` and `anti_cliches`
        # were missing from this list, which is precisely what a real 4B model did:
        # it obeyed the schema and lost the concept. tests/test_synthesis.py pins
        # the two lists against each other so they cannot drift apart again.
        "required": ["concept_title", "concept_thesis", "design_story",
                     "architectural_language", "spatial_organization",
                     "arrival_sequence", "circulation", "spatial_sequence",
                     "program", "structure", "materials", "lighting", "atmosphere",
                     "human_experience", "camera_recommendation",
                     "construction_character", "anti_cliches", "rationale"],
    }


def coerce_concept(raw: dict) -> StructuredArchitecturalConcept:
    """Shape repair only. Missing content stays missing so the validator can see it."""
    prog, struct = _sub(raw.get("program")), _sub(raw.get("structure"))
    mats, light = _sub(raw.get("materials")), _sub(raw.get("lighting"))
    cam = _sub(raw.get("camera_recommendation") or raw.get("camera"))

    seq: list[SpatialSequenceStep] = []
    for item in raw.get("spatial_sequence") or []:
        if isinstance(item, dict):
            step = _s(item.get("step") or item.get("name"))
            if step:
                seq.append(SpatialSequenceStep(
                    step=step, description=_s(item.get("description"))))
        elif _s(item):
            seq.append(SpatialSequenceStep(step=_s(item)))

    return StructuredArchitecturalConcept(
        **{f: _s(raw.get(f)) for f in _STR_FIELDS},
        **{f: _ls(raw.get(f)) for f in _LIST_FIELDS},
        spatial_sequence=seq,
        program=ProgramResolution(
            focal_space=_s(prog.get("focal_space")),
            focal_space_label=_s(prog.get("focal_space_label")),
            seating=_s(prog.get("seating")), walkway=_s(prog.get("walkway")),
            arrival=_s(prog.get("arrival")), circulation=_s(prog.get("circulation")),
            service_access=_s(prog.get("service_access")),
            back_of_house=_s(prog.get("back_of_house")),
            sightlines=_s(prog.get("sightlines")),
            spatial_hierarchy=_s(prog.get("spatial_hierarchy")),
            additional_zones=_ls(prog.get("additional_zones"))),
        structure=StructureBlock(
            structural_system=_s(struct.get("structural_system")),
            geometry=_s(struct.get("geometry")),
            mass_and_void=_s(struct.get("mass_and_void")),
            module=_s(struct.get("module")),
            spans_and_supports=_s(struct.get("spans_and_supports")),
            joints_and_assembly=_s(struct.get("joints_and_assembly"))),
        materials=MaterialsBlock(
            primary=_s(mats.get("primary")),
            material_behaviour=_s(mats.get("material_behaviour")),
            surface_treatment=_s(mats.get("surface_treatment")),
            secondary=_ls(mats.get("secondary")),
            palette_note=_s(mats.get("palette_note"))),
        lighting=LightingBlock(
            lighting_sources=_ls(light.get("lighting_sources")),
            colour_temperature=_s(light.get("colour_temperature")),
            height_and_distribution=_s(light.get("height_and_distribution")),
            shadow_behaviour=_s(light.get("shadow_behaviour")),
            interaction_with_materials=_s(light.get("interaction_with_materials"))),
        camera_recommendation=CameraRecommendation(
            viewpoint=_s(cam.get("viewpoint")), height=_s(cam.get("height")),
            lens=_s(cam.get("lens")), orientation=_s(cam.get("orientation")),
            distance=_s(cam.get("distance")), framing=_s(cam.get("framing")),
            time_of_day=_s(cam.get("time_of_day"))),
    )
