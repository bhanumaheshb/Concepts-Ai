from __future__ import annotations

from app.diversity.metric import (
    D_MIN, D_SOFT, COS_T, cosine, genotype_distance_detail, similarity, top_drivers,
)
from app.diversity.vendi import vendi_score
from app.domain.concept import ConceptDNA
from app.domain.diversity import DiversityMatrix, PairDriver
from app.ontology.graph import Ontology


def build_matrix(
    ont: Ontology, exploration_id: str, concepts: list[ConceptDNA], channels: list[str] | None = None
) -> DiversityMatrix:
    ids = [c.concept_id for c in concepts]
    n = len(concepts)
    dist = [[0.0] * n for _ in range(n)]
    drivers: list[PairDriver] = []
    for i in range(n):
        for j in range(i + 1, n):
            d, parts = genotype_distance_detail(ont, concepts[i].genotype, concepts[j].genotype)
            dist[i][j] = dist[j][i] = round(d, 6)
            drivers.append(PairDriver(a=ids[i], b=ids[j], distance=round(d, 4),
                                      top_facets=top_drivers(parts)))
    sim = [[similarity(dist[i][j]) for j in range(n)] for i in range(n)]
    pairs = [dist[i][j] for i in range(n) for j in range(i + 1, n)]
    return DiversityMatrix(
        exploration_id=exploration_id,
        concept_ids=ids,
        distances=dist,
        drivers=drivers,
        vendi_score=round(vendi_score(sim), 4) if n else 0.0,
        mean_pairwise=round(sum(pairs) / len(pairs), 4) if pairs else 0.0,
        min_pairwise=round(min(pairs), 4) if pairs else 0.0,
        channels_used=channels or ["GENOTYPE"],
    )


def min_distance_to(ont: Ontology, genotype, others: list) -> float:
    """Minimum genotype distance from one genotype to a list of genotypes."""
    if not others:
        return 1.0
    return min(genotype_distance_detail(ont, genotype, o)[0] for o in others)


def is_duplicate(
    ont: Ontology,
    a: ConceptDNA,
    b: ConceptDNA,
    vec_a: list[float] | None = None,
    vec_b: list[float] | None = None,
) -> tuple[bool, str | None]:
    """Channel 1 (genotype) always runs. Channel 2 (thesis embedding) is optional and
    may only ADD rejections, never remove one (spec R-DIV-02) — which makes
    V1-without-embeddings a strict behavioural subset of V2-with-them, so V1 tests
    stay valid when embeddings are switched on."""
    d, _ = genotype_distance_detail(ont, a.genotype, b.genotype)
    if d < D_MIN:
        return True, "GENOTYPE_TOO_CLOSE"
    if d < D_SOFT and vec_a and vec_b and cosine(vec_a, vec_b) > COS_T:
        return True, "SAME_IDEA_DIFFERENT_FACETS"
    return False, None
