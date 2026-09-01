from __future__ import annotations

from typing import Literal

from app.core.versions import VersionStamp
from app.domain.common import FacetId, Frozen, NicheRole
from app.domain.evaluation import EvaluationResult
from app.domain.genotype import ConceptGenotype
from app.domain.phenotype import ConceptPhenotype
from app.domain.reference import ReferenceContext


class Lineage(Frozen):
    parent_ids: list[str] = []
    operator: str | None = None
    magnitude: float | None = None
    pinned_facets: list[FacetId] = []
    generation: int = 0
    origin: Literal["ALLOCATED", "MUTATED", "HYBRIDISED", "REPAIRED"] = "ALLOCATED"


class RejectionRecord(Frozen):
    stage: str
    reason_code: str
    detail: str = ""


class ConceptDNA(Frozen):
    concept_id: str
    exploration_id: str
    niche_id: str
    niche_index: int = 0
    role: NicheRole = NicheRole.EXPLORATORY
    lineage: Lineage = Lineage()
    genotype: ConceptGenotype
    phenotype: ConceptPhenotype
    evaluation: EvaluationResult | None = None
    scene_graph_id: str | None = None
    prompt_compilation_ids: list[str] = []
    principle_id: str | None = None
    reference_context: "ReferenceContext | None" = None    # None for every non-reference run
    versions: VersionStamp
    status: Literal["DRAFT", "EVALUATED", "REPAIRING", "ACCEPTED", "REJECTED", "ABANDONED"] = "DRAFT"
    rejection: RejectionRecord | None = None
