"""Curriculum-constrained greedy portfolio selection.

Not DPP. At k=10 from a pool of ~14 with three role-mandated slots, greedy max-min
lands within noise of log-det — and its selection log is directly explainable to a
designer ("chosen over concept 12: 0.71 vs 0.68, driven by a larger minimum
distance"). A designer can disagree with that sentence, and their disagreement is
training data. Move to DPP in V2 when pools are larger and weights are learned.
"""
from __future__ import annotations

from app.core.ids import deterministic_id
from app.diversity.metric import D_MIN, genotype_distance
from app.domain.common import NicheRole
from app.domain.concept import ConceptDNA
from app.domain.diversity import DiversityMatrix
from app.domain.portfolio import Portfolio, PortfolioMember, SelectionStep
from app.ontology.graph import Ontology

MANDATORY = (NicheRole.CANONICAL, NicheRole.RADICAL, NicheRole.WILDCARD)
TARGET_HISTOGRAM = {
    NicheRole.CANONICAL: 1, NicheRole.ADJACENT: 3,
    NicheRole.EXPLORATORY: 4, NicheRole.RADICAL: 1, NicheRole.WILDCARD: 1,
}


def _q(c: ConceptDNA) -> float:
    return c.evaluation.quality_q if c.evaluation else 0.0


def _novelty(c: ConceptDNA) -> float:
    return c.evaluation.novelty.vs_platform if c.evaluation else 0.5


def _role_overflow(c: ConceptDNA, chosen: list[ConceptDNA], k: int) -> float:
    target = TARGET_HISTOGRAM.get(c.role, 1) * (k / 10.0)
    have = sum(1 for s in chosen if s.role == c.role)
    return max(0.0, have + 1 - target) / max(1.0, target)


def select_portfolio(
    ont: Ontology, exploration_id: str, candidates: list[ConceptDNA],
    matrix: DiversityMatrix, k: int,
) -> Portfolio:
    survivors = [c for c in candidates if c.evaluation and c.evaluation.gate_passed]
    chosen: list[ConceptDNA] = []
    log: list[SelectionStep] = []
    gaps: list[str] = []

    def min_dist(c: ConceptDNA, against: list[ConceptDNA]) -> float:
        if not against:
            return 1.0
        return min(genotype_distance(ont, c.genotype, s.genotype) for s in against)

    def score(c: ConceptDNA) -> float:
        return 0.45 * _q(c) + 0.40 * min_dist(c, chosen) + 0.15 * _novelty(c)

    # Role quotas are EXACT, not soft. The acceptance criterion is a specific
    # histogram, so a soft penalty that usually gets there is not good enough.
    scale = k / 10.0
    quotas = {r: max(0, round(n * scale)) for r, n in TARGET_HISTOGRAM.items()}
    while sum(quotas.values()) > k:
        biggest = max(quotas, key=lambda r: (quotas[r], r.value))
        quotas[biggest] -= 1
    while sum(quotas.values()) < k:
        quotas[NicheRole.EXPLORATORY] += 1

    # 1 — fill each role's quota from that role's survivors
    for role in (NicheRole.CANONICAL, NicheRole.RADICAL, NicheRole.WILDCARD,
                 NicheRole.ADJACENT, NicheRole.EXPLORATORY):
        want = quotas.get(role, 0)
        for _ in range(want):
            pool = [c for c in survivors if c.role == role and c not in chosen
                    and min_dist(c, chosen) >= D_MIN]
            if not pool:
                gaps.append(role.value)
                break
            ranked = sorted(pool, key=lambda c: (-score(c), c.concept_id))
            best = ranked[0]
            runner = ranked[1] if len(ranked) > 1 else None
            chosen.append(best)
            log.append(SelectionStep(
                step=len(log) + 1, chosen_id=best.concept_id, chosen_score=round(score(best), 4),
                runner_up_id=runner.concept_id if runner else None,
                runner_up_score=round(score(runner), 4) if runner else None,
                reason=f"role {role.value} quota {want}: q={_q(best):.2f} "
                       f"min_dist={min_dist(best, [x for x in chosen if x is not best]):.2f}",
            ))

    # 2 — backfill any shortfall from whatever survives, recording the substitution
    while len(chosen) < k:
        pool = [c for c in survivors if c not in chosen and min_dist(c, chosen) >= D_MIN]
        if not pool:
            break
        best = max(pool, key=lambda c: (score(c), c.concept_id))
        chosen.append(best)
        log.append(SelectionStep(step=len(log) + 1, chosen_id=best.concept_id,
                                 chosen_score=round(score(best), 4),
                                 reason=f"backfill for unmet role quota ({', '.join(sorted(set(gaps)))})"))

    chosen.sort(key=lambda c: c.niche_index)
    histogram = {r: sum(1 for c in chosen if c.role == r) for r in TARGET_HISTOGRAM}
    satisfied = len(chosen) == k and all(histogram[r] == quotas[r] for r in quotas)
    return Portfolio(
        portfolio_id=deterministic_id("pf", exploration_id),
        exploration_id=exploration_id,
        members=[PortfolioMember(concept_id=c.concept_id, role=c.role, rank=i + 1)
                 for i, c in enumerate(chosen)],
        diversity=matrix,
        curriculum_satisfied=satisfied,
        curriculum_gap=(", ".join(gaps) if gaps else
                        (None if satisfied else f"histogram {[(r.value, n) for r, n in histogram.items()]}")),
        selection_log=log,
    )
