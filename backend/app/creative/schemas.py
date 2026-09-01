"""Schemas for LLM input/output. Exported to JSON Schema and handed to the model,
so the contract in `domain` and the contract with the model are the same object."""
from __future__ import annotations

from app.domain.common import Frozen, Severity
from app.domain.evaluation import EvidenceSpan


class ProgramProposal(Frozen):
    """What the model adds on top of deterministic parsing."""
    summary: str
    soft_intents: list[str] = []
    inferred_constraints: list[str] = []


class CriticFindingProposal(Frozen):
    code: str
    severity: Severity
    statement: str
    evidence: list[EvidenceSpan] = []
    facet_ref: str | None = None
    repair_hint: str | None = None


class CriticLLMOutput(Frozen):
    """The model emits findings with evidence. It does NOT emit a score — the score
    is derived in code from the finding set, so it is comparable across releases and
    cannot drift with prompt wording."""
    findings: list[CriticFindingProposal] = []
    notes: str = ""


class SceneZoneProposal(Frozen):
    zone: str
    role: str = ""
    area_m2: float
    capacity: int = 0
    level_m: float = 0.0


class SceneGraphProposal(Frozen):
    zones: list[SceneZoneProposal] = []
    focal_role: str = "focal"
    focal_clearance_radial_m: float = 1.5
    focal_clearance_overhead_m: float = 3.5
    element_height_m: float = 3.0
    element_span_m: float = 6.0
    notes: list[str] = []
