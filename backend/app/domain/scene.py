"""Scene graph v1 — lightweight but *dimensioned*.

Not BIM. Enough typed, metric structure to feed the prompt compiler real numbers,
run four validity checks, and keep the future procedural-3D path reachable.
"""
from __future__ import annotations

from typing import Literal

from app.domain.common import Frozen

Primitive = Literal[
    "EXTRUDED_POLYGON", "STEPPED_REVOLVE", "COLONNADE", "CATENARY_SURFACE",
    "PLANAR_SLAB", "SHELL_VAULT", "MAST_AND_CABLE", "STACKED_MASS", "VOID_CUT",
]


class SiteFrame(Frozen):
    width_m: float
    depth_m: float
    ground: str = "LAWN"
    orientation_deg: float = 0.0


class SceneNode(Frozen):
    id: str
    type: Literal["zone", "element", "focal", "circulation", "light", "camera", "occupancy"]
    role: str = ""
    parent: str | None = None
    # geometry / dimensions (units: metres)
    primitive: Primitive | None = None
    x_m: float = 0.0
    y_m: float = 0.0
    level_m: float = 0.0
    width_m: float | None = None
    depth_m: float | None = None
    radius_m: float | None = None
    height_m: float | None = None
    span_m: float | None = None
    area_m2: float | None = None
    capacity: int | None = None
    material_ref: str | None = None
    structural_role: str | None = None
    # focal
    clearance_radial_m: float | None = None
    clearance_overhead_m: float | None = None
    invariant_ref: str | None = None
    # light
    instrument: str | None = None
    count: int | None = None
    cct_k: int | None = None
    # camera
    lens_mm: float | None = None
    eye_height_m: float | None = None
    look_at: str | None = None
    view_role: str | None = None
    # occupancy
    group: str | None = None
    posture: str | None = None
    notes: list[str] = []


class SceneEdge(Frozen):
    type: Literal["contains", "supports", "adjacent", "circulation", "sightline", "illuminates"]
    src: str
    dst: str
    width_m: float | None = None


class SceneCheck(Frozen):
    name: str
    passed: bool
    detail: str = ""


class SceneDerived(Frozen):
    total_zone_area_m2: float = 0.0
    total_capacity: int = 0
    max_span_m: float = 0.0
    cost_band: int = 3
    build_days: float = 0.0
    crew: int = 0


class SceneGraph(Frozen):
    scene_graph_id: str
    concept_id: str
    units: str = "m"
    schema_version: str = "1.0.0"
    status: Literal["COMPLETE", "PARTIAL", "FAILED"] = "COMPLETE"
    site: SiteFrame
    nodes: list[SceneNode] = []
    edges: list[SceneEdge] = []
    derived: SceneDerived = SceneDerived()
    checks: list[SceneCheck] = []
    unresolved: list[str] = []

    def node(self, node_id: str) -> SceneNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def by_type(self, t: str) -> list[SceneNode]:
        return [n for n in self.nodes if n.type == t]

    def camera(self, view_role: str) -> SceneNode | None:
        return next((n for n in self.nodes if n.type == "camera" and n.view_role == view_role), None)

    def digest_parts(self) -> list[str]:
        return [
            f"{n.id}:{n.type}:{n.primitive}:{n.width_m}:{n.depth_m}:{n.radius_m}:{n.height_m}"
            for n in sorted(self.nodes, key=lambda n: n.id)
        ]
