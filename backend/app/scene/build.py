"""Scene graph v1 — lightweight but dimensioned.

The LLM proposes zone areas and capacities under a strict schema; a deterministic
solver then places, dimensions, quantifies and validates. Failure is NON-FATAL: a
concept whose geometry cannot be resolved is still a valid creative output, so it
yields status=PARTIAL and the prompt compiler degrades (spec R-SCENE-01).
"""
from __future__ import annotations

import math

from app.core.ids import deterministic_id
from app.core.seeded import SeededRandom
from app.core.versions import SCENE_SCHEMA_VERSION
from app.creative.context import SceneContext
from app.creative.schemas import SceneGraphProposal
from app.domain.brief import DesignProgram
from app.domain.common import ModelTier
from app.domain.genotype import ConceptGenotype
from app.domain.providers.protocols import LLMProvider, PromptBlock, PromptEnvelope
from app.domain.scene import (
    SceneCheck, SceneDerived, SceneEdge, SceneGraph, SceneNode, SiteFrame,
)
from app.ontology.graph import Ontology

AREA_PER_PERSON = {"seated": 0.9, "standing": 0.6, "dining": 1.6}
CREW_PER_100M2 = 4


def _propose(llm: LLMProvider, ont: Ontology, g: ConceptGenotype,
             program: DesignProgram, seed: int) -> tuple[SceneGraphProposal, int]:
    envelope = PromptEnvelope(
        prompt_id="scene.propose", version="1.0.0",
        blocks=[
            PromptBlock(role="system", cacheable=True,
                        text="Propose zones with real areas in square metres. Dimensions must fit "
                             "the site. Return only the schema."),
            PromptBlock(role="user", cacheable=True, text=f"PROGRAMME\n{program.summary}"),
            PromptBlock(role="user", cacheable=False,
                        text="GENOTYPE\n" + "\n".join(f"{k}: {v}" for k, v in g.as_display_rows())),
        ],
        schema_ref="SceneGraphProposal", tier=ModelTier.CRITIQUE, max_output_tokens=2048,
    )
    resp = llm.complete_structured(envelope=envelope, schema=SceneGraphProposal, seed=seed,
                                   context=SceneContext(genotype=g, program=program))
    return resp.value, 1


def build_scene_graph(
    llm: LLMProvider, ont: Ontology, concept_id: str, g: ConceptGenotype,
    program: DesignProgram, seed: int,
) -> tuple[SceneGraph, int]:
    rng = SeededRandom(seed, "scene", concept_id)
    site = SiteFrame(width_m=program.site.width_m, depth_m=program.site.depth_m,
                     ground=program.site.ground, orientation_deg=program.site.orientation_deg)
    unresolved: list[str] = []
    calls = 0
    try:
        proposal, calls = _propose(llm, ont, g, program, seed)
    except Exception as exc:                       # non-fatal by design
        return SceneGraph(
            scene_graph_id=deterministic_id("sg", concept_id), concept_id=concept_id,
            status="FAILED", site=site, schema_version=SCENE_SCHEMA_VERSION,
            unresolved=[f"proposal failed: {exc}"],
        ), calls

    primitive = ont.node(g.geometry.system).primitive or "EXTRUDED_POLYGON"
    nodes: list[SceneNode] = []
    edges: list[SceneEdge] = []

    # ---- place zones as full-width bands stacked down the site ----
    # Shelf packing wastes ~half the plot and silently drops zones on tight indoor
    # sites; banding always fits whenever the total area fits, which is what the
    # alignment critic actually cares about.
    usable = program.site.usable_area_m2
    inner_w = max(2.0, site.width_m - 2.0)
    inner_d = max(2.0, site.depth_m - 2.0)
    proposed = [(z, max(6.0, z.area_m2)) for z in proposal.zones]
    total_proposed = sum(a for _, a in proposed) or 1.0
    capacity_area = inner_w * inner_d * 0.85
    scale = min(1.0, capacity_area / total_proposed)

    cursor_y = 1.0
    total_area = 0.0
    total_capacity = 0
    for z, raw_area in sorted(proposed, key=lambda t: -t[1]):
        area = raw_area * scale
        d = max(1.5, area / inner_w)
        if cursor_y + d > site.depth_m - 1.0:
            d = max(1.5, (site.depth_m - 1.0) - cursor_y)
            if d < 1.5:
                unresolved.append(f"zone '{z.zone}' does not fit the site")
                continue
        nodes.append(SceneNode(
            id=f"zone_{z.zone}", type="zone", role=z.zone, primitive="EXTRUDED_POLYGON",
            x_m=1.0, y_m=round(cursor_y, 2), level_m=z.level_m,
            width_m=round(inner_w, 2), depth_m=round(d, 2), area_m2=round(inner_w * d, 2),
            capacity=z.capacity,
        ))
        total_area += inner_w * d
        total_capacity += z.capacity
        cursor_y += d + 0.5

    if not nodes:
        return SceneGraph(
            scene_graph_id=deterministic_id("sg", concept_id), concept_id=concept_id,
            status="FAILED", site=site, schema_version=SCENE_SCHEMA_VERSION,
            unresolved=unresolved or ["no zone could be placed"],
        ), calls

    # the signature element belongs at the programme's PRIMARY zone, not merely the
    # largest one — otherwise the prompt describes the seating rather than the ceremony
    PRIMARY_ROLES = ("ceremony", "stage", "main", "gallery", "shelter", "dining")
    main = next((n for r in PRIMARY_ROLES for n in nodes if n.role == r),
                max(nodes, key=lambda n: n.area_m2 or 0.0))

    # ---- the signature element, dimensioned from the genotype's geometry ----
    material_span = ont.node(g.primary_material().material).span or 99.0
    struct_span = ont.node(g.structural_logic.value).span or 99.0
    # size the element to what this concept can actually build, floored by the
    # programme's own requirement so a genuine impossibility still surfaces
    required_clear = min(main.width_m or 6.0, main.depth_m or 6.0) * 0.6
    span = max(2.0, min(float(proposal.element_span_m), material_span, struct_span))
    if required_clear > max(material_span, struct_span):
        span = round(required_clear, 2)     # genuinely impossible -> let the critic fire
    height = float(proposal.element_height_m)
    if g.scale_strategy.value.endswith("monumental"):
        height *= 1.8
    elif g.scale_strategy.value.endswith("landscape"):
        height *= 2.4
    elif g.scale_strategy.value.endswith("miniature"):
        height *= 0.6
    element = SceneNode(
        id="element_signature", type="element", role="signature", parent=main.id,
        primitive=primitive, x_m=main.x_m, y_m=main.y_m,
        width_m=main.width_m, depth_m=main.depth_m,
        height_m=round(height, 2), span_m=round(span, 2),
        material_ref=g.primary_material().material,
        structural_role=g.structural_logic.value,
        level_m=main.level_m,
    )
    nodes.append(element)
    edges.append(SceneEdge(type="contains", src=main.id, dst=element.id))

    # ---- focal node, traceable to the invariant it satisfies ----
    sacred = next((c for c in program.invariants if c.sacred), None)
    focal = SceneNode(
        id="focal_point", type="focal", role=proposal.focal_role, parent=main.id,
        x_m=round(main.x_m + (main.width_m or 4) / 2, 2),
        y_m=round(main.y_m + (main.depth_m or 4) / 2, 2), level_m=main.level_m,
        radius_m=0.6, height_m=0.4,
        clearance_radial_m=proposal.focal_clearance_radial_m,
        clearance_overhead_m=proposal.focal_clearance_overhead_m,
        invariant_ref=sacred.constraint_id if sacred else None,
    )
    nodes.append(focal)
    edges.append(SceneEdge(type="contains", src=main.id, dst=focal.id))

    # ---- lighting, occupancy, camera ----
    lamp_count = 40 if "field" not in g.lighting_philosophy.value else 380
    nodes.append(SceneNode(
        id="light_primary", type="light", role="primary",
        instrument=g.lighting_philosophy.value.split(":")[-1], count=lamp_count,
        cct_k=1900 if "flame" in ont.node(g.lighting_philosophy.value).parent or "" else 3000,
        parent=main.id,
    ))
    edges.append(SceneEdge(type="illuminates", src="light_primary", dst=element.id))
    nodes.append(SceneNode(
        id="occupancy_guests", type="occupancy", role="guests", group="guests",
        count=program.capacity.guests, parent=main.id,
        posture="seated" if program.capacity.seated else "standing",
    ))
    cam = SceneNode(
        id="camera_hero", type="camera", role="hero", view_role="HERO",
        x_m=round(min(site.width_m - 1.0, main.x_m + (main.width_m or 6) * 1.6), 2),
        y_m=round(max(1.0, main.y_m - (main.depth_m or 6) * 0.5), 2),
        lens_mm=35.0, eye_height_m=1.6, look_at=focal.id,
    )
    nodes.append(cam)
    edges.append(SceneEdge(type="sightline", src="occupancy_guests", dst=focal.id))

    # ---- derived quantities ----
    cost_band = max(ont.node(r).cost for r in g.all_refs() if r in ont.nodes)
    build_days = round(total_area / 60.0 * (1.0 + 0.25 * cost_band), 2)
    derived = SceneDerived(
        total_zone_area_m2=round(total_area, 2), total_capacity=total_capacity,
        max_span_m=round(span, 2), cost_band=cost_band, build_days=build_days,
        crew=max(2, int(total_area / 100 * CREW_PER_100M2)),
    )

    # ---- the four checks ----
    checks = [
        SceneCheck(name="fit", passed=total_area <= usable and not unresolved,
                   detail=f"{total_area:.0f} m² placed on {usable:.0f} m² site"),
        SceneCheck(name="capacity", passed=total_capacity >= program.capacity.guests,
                   detail=f"{total_capacity} vs {program.capacity.guests} required"),
        SceneCheck(name="focal_clearance",
                   passed=(focal.clearance_radial_m or 0) <= (main.width_m or 0) / 2,
                   detail=f"radial {focal.clearance_radial_m} m within zone half-width"),
        SceneCheck(name="sightline",
                   passed=(element.height_m or 0) < 12.0 and main.level_m <= 0.5,
                   detail=f"element height {element.height_m} m, zone level {main.level_m} m"),
    ]
    status = "COMPLETE" if not unresolved and all(c.passed for c in checks[:1]) else "PARTIAL"
    return SceneGraph(
        scene_graph_id=deterministic_id("sg", concept_id), concept_id=concept_id,
        status=status, site=site, nodes=nodes, edges=edges, derived=derived,
        checks=checks, unresolved=unresolved, schema_version=SCENE_SCHEMA_VERSION,
    ), calls
