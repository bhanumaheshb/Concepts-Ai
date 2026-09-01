from __future__ import annotations

from app.domain.common import Frozen


class PairDriver(Frozen):
    a: str
    b: str
    distance: float
    top_facets: list[tuple[str, float]] = []


class DiversityMatrix(Frozen):
    exploration_id: str
    concept_ids: list[str]
    distances: list[list[float]]
    drivers: list[PairDriver] = []
    vendi_score: float = 0.0
    mean_pairwise: float = 0.0
    min_pairwise: float = 0.0
    metric_version: str = "1.0.0"
    channels_used: list[str] = ["GENOTYPE"]

    def min_distance_for(self, concept_id: str) -> float:
        if concept_id not in self.concept_ids or len(self.concept_ids) < 2:
            return 0.0
        i = self.concept_ids.index(concept_id)
        return min(self.distances[i][j] for j in range(len(self.concept_ids)) if j != i)
