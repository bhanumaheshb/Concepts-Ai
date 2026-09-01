from __future__ import annotations

from app.domain.common import Frozen, NicheRole, OntologyRef
from app.domain.genotype import PartialGenotype


class Niche(Frozen):
    niche_id: str
    exploration_id: str
    index: int
    role: NicheRole
    skeleton: PartialGenotype
    required: list[OntologyRef] = []
    forbidden: list[OntologyRef] = []
    injected_principles: list[str] = []
    target_band: tuple[float, float] = (0.0, 1.0)
    distance_to_canonical: float = 0.0
    allocation_rank: int = 0
    seed: int = 0
    domain_override: dict[str, list[str]] = {}   # facet -> restricted values (from principle)
    score_breakdown: dict[str, float] = {}
