"""Conceptual distance.

Deterministic, offline, and independent of any model. This is the component that
decides whether two concepts are genuinely different, so it is the first thing to
unit-test and the last thing to change casually.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.common import ACTIVE_FACETS
from app.domain.genotype import ConceptGenotype
from app.ontology.graph import Ontology

SIGMA = 0.35
D_MIN = 0.35     # hard duplicate threshold
D_SOFT = 0.45    # band in which optional channels are consulted
COS_T = 0.92


# ---------- per-type distance functions ----------

def d_tree(ont: Ontology, a: str, b: str) -> float:
    """Wu-Palmer over the ontology. Categorical (flat) facets are the degenerate
    case of this function, not a separate one."""
    if a == b:
        return 0.0
    da, db = ont.depth(a), ont.depth(b)
    if da + db == 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (2.0 * ont.lca_depth(a, b)) / (da + db)))


def d_ordered(ont: Ontology, facet: str, a: str, b: str) -> float:
    n = ont.order_len(facet)
    return abs(ont.rank(facet, a) - ont.rank(facet, b)) / max(1, n - 1)


def d_weighted_set(a: list[tuple[str, float]], b: list[tuple[str, float]]) -> float:
    """Weighted Jaccard over material shares. A 5% brass accent moves the needle
    far less than a swapped 55% primary — the 'more flowers' case."""
    keys = {k for k, _ in a} | {k for k, _ in b}
    if not keys:
        return 0.0
    da, db = dict(a), dict(b)
    num = sum(min(da.get(k, 0.0), db.get(k, 0.0)) for k in keys)
    den = sum(max(da.get(k, 0.0), db.get(k, 0.0)) for k in keys)
    return 1.0 - (num / den) if den > 0 else 0.0


def d_ordered_seq(a: list[str], b: list[str]) -> float:
    """Longest common subsequence, so membership *and* order both count."""
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            dp[i + 1][j + 1] = dp[i][j] + 1 if a[i] == b[j] else max(dp[i][j + 1], dp[i + 1][j])
    return 1.0 - dp[m][n] / max(m, n)


def d_numeric(a: float, b: float, rng: float) -> float:
    return min(1.0, abs(a - b) / rng) if rng > 0 else 0.0


# ---------- facet-level dispatch ----------

@dataclass(frozen=True)
class FacetDistance:
    facet: str
    delta: float
    weight: float

    @property
    def contribution(self) -> float:
        return self.delta * self.weight


def _materials(g: ConceptGenotype) -> list[tuple[str, float]]:
    return [(m.material, m.share) for m in g.material_palette]


def facet_delta(ont: Ontology, facet: str, a: ConceptGenotype, b: ConceptGenotype) -> float | None:
    if facet == "material_palette":
        return d_weighted_set(_materials(a), _materials(b))
    if facet == "spatial_narrative":
        return d_ordered_seq(list(a.spatial_narrative), list(b.spatial_narrative))
    if facet == "geometry_system":
        # Parameters only discriminate *within* a system, and even then only mildly.
        if a.geometry.system != b.geometry.system:
            return d_tree(ont, a.geometry.system, b.geometry.system)
        pa = {p.name: p.value for p in a.geometry.params}
        pb = {p.name: p.value for p in b.geometry.params}
        shared = set(pa) & set(pb)
        if not shared:
            return 0.0
        deltas = [d_numeric(pa[k], pb[k], max(1e-6, abs(pa[k]) + abs(pb[k]))) for k in sorted(shared)]
        return 0.4 * (sum(deltas) / len(deltas))
    if facet == "scale_strategy":
        return d_ordered(ont, facet, a.scale_strategy.value, b.scale_strategy.value)
    va, vb = a.facet_value(facet), b.facet_value(facet)
    if va is None or vb is None:
        return None                      # missing => dropped from both sides
    return d_tree(ont, va, vb)


def genotype_distance_detail(
    ont: Ontology, a: ConceptGenotype, b: ConceptGenotype
) -> tuple[float, list[FacetDistance]]:
    parts: list[FacetDistance] = []
    num = den = 0.0
    for facet in ACTIVE_FACETS:
        w = ont.weight(facet)
        if w <= 0:
            continue
        delta = facet_delta(ont, facet, a, b)
        if delta is None:
            continue                     # renormalise rather than penalise
        parts.append(FacetDistance(facet, delta, w))
        num += delta * w
        den += w
    return (num / den if den > 0 else 0.0), parts


def genotype_distance(ont: Ontology, a: ConceptGenotype, b: ConceptGenotype) -> float:
    return genotype_distance_detail(ont, a, b)[0]


def top_drivers(parts: list[FacetDistance], n: int = 3) -> list[tuple[str, float]]:
    ranked = sorted(parts, key=lambda p: p.contribution, reverse=True)[:n]
    return [(p.facet, round(p.contribution, 4)) for p in ranked if p.delta > 0]


def similarity(d: float) -> float:
    return math.exp(-(d * d) / (2 * SIGMA * SIGMA))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
