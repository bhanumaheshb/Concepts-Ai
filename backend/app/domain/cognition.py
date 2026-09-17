"""Contracts for the Creative Cognition layer.

The layer decides WHAT conceptual transformation should happen; the existing
genotype operators in `app/mutation/operators.py` decide HOW it is applied. A
`CreativeTransformation` is the handover between those two — a structured
proposal, never prose, and never a finished design.

Nothing here reasons. These are contracts only, at the bottom of the stack
alongside every other domain model.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.domain.common import Frozen, Score


class CognitiveOperation(StrEnum):
    """The nine conceptual operations.

    Distinct from the genotype operators they dispatch to: REINTERPRET is a way of
    re-reading the brief, `op_reinterpret` is a facet substitution. One conceptual
    operation may drive different genotype operators depending on what it decides.
    """
    REINTERPRET = "REINTERPRET"
    INVERT = "INVERT"
    DISTORT = "DISTORT"
    REMOVE = "REMOVE"
    SCALE = "SCALE"
    HYBRIDISE = "HYBRIDISE"
    ASSOCIATE = "ASSOCIATE"
    SEQUENCE = "SEQUENCE"
    EVOLVE = "EVOLVE"


class FeasibilityRisk(StrEnum):
    """A speculative concept is allowed. A silently invalid one is not."""
    VALID = "VALID"        # no constraint violated
    RISKY = "RISKY"        # buildable but demanding; carries a stated risk
    REJECTED = "REJECTED"  # violates a hard constraint; kept only for the trace


class CreativeTransformation(Frozen):
    """One proposed conceptual move, checkable before anything is built.

    `genotype_operation` names an operator that must already exist in the mutation
    REGISTRY. The cognition layer never mutates a genotype itself — that keeps the
    deterministic layer the only thing that can change a concept.
    """
    transformation_id: str
    operation: CognitiveOperation
    source_concept_id: str
    parent_id: str | None = None
    second_parent_id: str | None = None        # HYBRIDISE only

    # What is being acted on, and what it becomes.
    assumption_or_principle: str = Field(min_length=3)
    transformation: str = Field(min_length=3)
    new_principle: str = Field(min_length=3)
    spatial_or_design_consequence: str = Field(min_length=3)

    # How the deterministic layer should execute it.
    genotype_operation: str = ""               # a key in mutation.REGISTRY
    target_facet: str = ""
    magnitude: float = 0.5

    reference_ids: list[str] = []
    novelty_rationale: str = ""
    feasibility_risk: FeasibilityRisk = FeasibilityRisk.VALID
    constraint_violations: list[str] = []      # constraint_ids, never free text
    confidence: Score = 0.5

    @property
    def executable(self) -> bool:
        """A REJECTED transformation is recorded for the trace but never applied."""
        return (self.feasibility_risk is not FeasibilityRisk.REJECTED
                and not self.constraint_violations)


class CognitionRecord(Frozen):
    """Observability for one operation — why a concept exists, without storing
    the model's reasoning. Concise structured facts only."""
    transformation_id: str
    operation: CognitiveOperation
    parent_id: str | None = None
    child_concept_id: str | None = None        # None => the mutation produced nothing
    genotype_operation: str = ""
    genotype_status: str = ""                  # APPLIED | NO_OP | INFEASIBLE | ...
    generation: int = 0
    novelty_score: float = 0.0
    conceptual_distance: float = 0.0
    feasibility_risk: FeasibilityRisk = FeasibilityRisk.VALID
    rejection_reason: str = ""
    selected: bool = False
