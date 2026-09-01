from __future__ import annotations

from app.domain.common import Frozen, NicheRole
from app.domain.diversity import DiversityMatrix


class SelectionStep(Frozen):
    step: int
    chosen_id: str
    chosen_score: float
    runner_up_id: str | None = None
    runner_up_score: float | None = None
    reason: str = ""


class PortfolioMember(Frozen):
    concept_id: str
    role: NicheRole
    rank: int


class Portfolio(Frozen):
    portfolio_id: str
    exploration_id: str
    members: list[PortfolioMember]
    diversity: DiversityMatrix
    curriculum_satisfied: bool = True
    curriculum_gap: str | None = None
    selection_log: list[SelectionStep] = []
