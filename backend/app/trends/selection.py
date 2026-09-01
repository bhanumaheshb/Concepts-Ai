"""TRD-05 — diverse selection.

Not top-N by score. Greedy max-marginal-relevance with a domain term, the same shape as
portfolio selection, so ten references never arrive from one domain.
"""
from __future__ import annotations

from app.domain.trend import TrendCandidate, TrendDomainPlan

W_SCORE, W_DOMAIN = 0.62, 0.38


def domain_novelty(candidate: TrendCandidate, chosen: list[TrendCandidate]) -> float:
    used = sum(1 for c in chosen if c.domain is candidate.domain)
    return 1.0 / (1.0 + used)          # 1.0 unused, 0.5 second, 0.33 third


def select_diverse(candidates: list[TrendCandidate], k: int,
                   plan: list[TrendDomainPlan]) -> list[TrendCandidate]:
    """Target shares come from the plan's own priorities — adaptive, never a hardcoded
    3/2/2/1 split."""
    priority = {p.domain: p.priority for p in plan}
    pool = sorted(candidates, key=lambda c: (-c.score, c.candidate_id))
    chosen: list[TrendCandidate] = []
    while pool and len(chosen) < k:
        best, best_v = None, -1.0
        for c in pool:
            v = (W_SCORE * c.score
                 + W_DOMAIN * domain_novelty(c, chosen) * (0.5 + 0.5 * priority.get(c.domain, 0.5)))
            if v > best_v:
                best, best_v = c, v
        assert best is not None
        chosen.append(best)
        pool.remove(best)
    return chosen
