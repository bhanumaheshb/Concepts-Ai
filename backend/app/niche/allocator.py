"""Niche allocation — the core of the divergence thesis.

Ten coordinates are chosen BEFORE any concept is written. The allocator solves
candidate genotypes, measures them against the already-committed set with the
distance metric, and keeps the one that best satisfies its role's distance band.

Deterministic given a seed: identical (space, antibrief, k, seed) yields identical
niches, with all randomness drawn from SeededRandom substreams (spec R-ALLOC-01).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.ids import deterministic_id
from app.core.seeded import SeededRandom
from app.diversity.metric import D_MIN, genotype_distance
from app.domain.antibrief import AntiBrief
from app.domain.common import ACTIVE_FACETS, NicheRole
from app.domain.genotype import ConceptGenotype, PartialGenotype
from app.domain.niche import Niche
from app.domain.space import CreativeSearchSpace
from app.genotype.solve import SolveFailed, solve_genotype
from app.niche.principles import principle_overrides, select_principle
from app.ontology.graph import Ontology, Principle
from app.space.csp import incoherence_prior

BANDS: dict[NicheRole, tuple[float, float]] = {
    NicheRole.CANONICAL: (0.0, 0.0),
    NicheRole.ADJACENT: (0.25, 0.45),
    NicheRole.EXPLORATORY: (0.45, 0.70),
    NicheRole.RADICAL: (0.70, 1.00),
    NicheRole.WILDCARD: (0.35, 1.00),
}
CANDIDATES: dict[NicheRole, int] = {
    NicheRole.ADJACENT: 90,
    NicheRole.EXPLORATORY: 160,   # largest quota and the tightest band
    NicheRole.RADICAL: 160,
    NicheRole.WILDCARD: 90,
}
TOP_WEIGHTED_FACETS = ("architectural_language", "geometry_system", "thesis_archetype", "structural_logic")


@dataclass
class Allocation:
    niches: list[Niche]
    genotypes: list[ConceptGenotype]
    principles: list[Principle | None]
    degraded: list[str]


def expand_pool(k: int) -> list[NicheRole]:
    """Allocate MORE niches than the portfolio needs.

    Concepts fail gates; without a buffer a portfolio silently shrinks below k, which
    is a worse failure than a slightly larger spend. ~1.5k candidates for k=10, with
    two of each mandatory role so a single gate failure cannot cost the curriculum.
    """
    if k == 10:
        # Order matters more than count. Every niche must clear D_MIN against every
        # niche already placed, so a tightly pruned space SATURATES and whatever is
        # allocated last becomes unplaceable. The pool therefore places the EXACT
        # target curriculum first, while the space is still open, and only then adds
        # spares as insurance against gate failures.
        C, E, A, R, W = (NicheRole.CANONICAL, NicheRole.EXPLORATORY,
                         NicheRole.ADJACENT, NicheRole.RADICAL, NicheRole.WILDCARD)
        # EXPLORATORY is both the largest quota (4) and the hardest to place — it needs
        # a mid-radius band, an injected principle, and D_MIN clearance — so all four go
        # first. ADJACENT sits near the canonical and RADICAL/WILDCARD have the whole
        # outer space, so they tolerate a saturated field.
        target = [C, E, E, E, E, A, A, A, R, W]          # 1/3/4/1/1
        spares = [E, E, A, A, R, W, C]                   # insurance, failure survivable
        return target + spares
    base = expand_curriculum(k)
    extra = [NicheRole.ADJACENT, NicheRole.EXPLORATORY][: max(0, k // 4)]
    mandatory_spare = [NicheRole.RADICAL, NicheRole.WILDCARD] if k >= 6 else []
    return base + extra + mandatory_spare


def expand_curriculum(k: int) -> list[NicheRole]:
    """1 canonical / 3 adjacent / 4 exploratory / 1 radical / 1 wildcard at k=10,
    scaled proportionally for other k."""
    if k == 10:
        return ([NicheRole.CANONICAL] + [NicheRole.ADJACENT] * 3 + [NicheRole.EXPLORATORY] * 4
                + [NicheRole.RADICAL, NicheRole.WILDCARD])
    roles = [NicheRole.CANONICAL]
    remaining = max(0, k - 1)
    n_adj = max(1, round(remaining * 0.375)) if remaining >= 3 else remaining
    n_exp = max(1, round(remaining * 0.5)) if remaining >= 4 else 0
    n_rad = 1 if remaining - n_adj - n_exp >= 2 else 0
    n_wild = max(0, remaining - n_adj - n_exp - n_rad)
    roles += ([NicheRole.ADJACENT] * n_adj + [NicheRole.EXPLORATORY] * n_exp
              + [NicheRole.RADICAL] * n_rad + [NicheRole.WILDCARD] * n_wild)
    return roles[:k]


def band_fit(d: float, band: tuple[float, float]) -> float:
    lo, hi = band
    if lo <= d <= hi:
        return 1.0
    gap = (lo - d) if d < lo else (d - hi)
    return max(0.0, 1.0 - gap * 3.0)


def novelty(ont: Ontology, g: ConceptGenotype, archive: list[ConceptGenotype], k: int = 5) -> float:
    if not archive:
        return 1.0
    ds = sorted(genotype_distance(ont, g, a) for a in archive)[:k]
    return sum(ds) / len(ds)


def cliche_overlap(g: ConceptGenotype, antibrief: AntiBrief) -> float:
    refs = set(g.all_refs())
    if not antibrief.cliche_clusters:
        return 0.0
    worst = 0.0
    for c in antibrief.cliche_clusters:
        hit = len(refs & set(c.facet_values))
        if hit >= 1:
            worst = max(worst, (hit / max(1, len(c.facet_values))) * c.prevalence)
    return worst


def _role_bonus(ont: Ontology, g: ConceptGenotype, role: NicheRole,
                canonical: ConceptGenotype | None, principle: Principle | None) -> float:
    if role == NicheRole.RADICAL and canonical is not None:
        for facet in ACTIVE_FACETS:
            cv, gv = canonical.facet_value(facet), g.facet_value(facet)
            if cv and gv and gv in ont.inverse_of(cv):
                return 1.0
        return 0.0
    if role == NicheRole.EXPLORATORY:
        return 1.0 if principle is not None else 0.0
    return 0.0


def _cluster_hits(g: ConceptGenotype, antibrief: AntiBrief) -> list[str]:
    refs = set(g.all_refs())
    return [c.cluster_id for c in antibrief.cliche_clusters if len(refs & set(c.facet_values)) >= 2]


def allocate(
    ont: Ontology,
    space: CreativeSearchSpace,
    antibrief: AntiBrief,
    exploration_id: str,
    k: int,
    seed: int,
    archive: list[ConceptGenotype] | None = None,
    injection=None,
) -> Allocation:
    archive = archive or []
    # Reference principles are assigned per role BEFORE the loop (R-REF-20), so four
    # exploratory niches draw from four different reference dimensions rather than
    # repeating the highest-salience one.
    ref_by_role: dict[str, list] = {}
    role_cursor: dict[str, int] = {}
    if injection is not None:
        by_id = {p.id: p for p in injection.principles}
        for role_value, pids in (injection.niche_assignment or {}).items():
            ref_by_role[role_value] = [by_id[i] for i in pids if i in by_id]
    rng = SeededRandom(seed, "allocate", exploration_id)
    roles = expand_pool(k)
    cliche_values = antibrief.all_cliche_values()
    principle_usage: dict[str, int] = {}
    degraded: list[str] = []

    niches: list[Niche] = []
    genotypes: list[ConceptGenotype] = []
    principles: list[Principle | None] = []
    cluster_occupancy: dict[str, int] = {}

    # ── 1. canonical: the cliché, executed well. EVERY canonical slot is seeded from
    #        the anti-brief — a spare canonical that is merely a random genotype
    #        labelled CANONICAL would defeat the point of the slot.
    n_canonical = sum(1 for r in roles if r == NicheRole.CANONICAL)
    canonical_g: ConceptGenotype | None = None
    for slot in range(n_canonical):
        solved: ConceptGenotype | None = None
        for attempt in range(4):
            try:
                solved = solve_genotype(
                    ont, space, rng.substream("canonical", slot, attempt),
                    skeleton=antibrief.canonical_seed,
                    cliche_values=cliche_values, cliche_bonus=1.2,
                )
                break
            except SolveFailed:
                continue
        if solved is None:
            if slot == 0:
                solved = solve_genotype(ont, space, rng.substream("canonical_fallback"))
                degraded.append("canonical_seed_infeasible")
            else:
                continue
        if slot > 0 and canonical_g is not None and genotype_distance(ont, solved, canonical_g) < D_MIN:
            continue                       # near-clones waste a slot and block each other's repair
        if canonical_g is None:
            canonical_g = solved
        genotypes.append(solved)
        principles.append(None)
        for cid in _cluster_hits(solved, antibrief):
            cluster_occupancy[cid] = cluster_occupancy.get(cid, 0) + 1
        niches.append(Niche(
            niche_id=deterministic_id("nc", exploration_id, slot), exploration_id=exploration_id,
            index=slot, role=NicheRole.CANONICAL, skeleton=antibrief.canonical_seed,
            target_band=BANDS[NicheRole.CANONICAL],
            distance_to_canonical=round(genotype_distance(ont, solved, canonical_g), 4),
            allocation_rank=slot, seed=seed,
            score_breakdown={"seeded_from_antibrief": 1.0},
        ))

    # ── 2. farthest-point traversal for the remaining slots ──
    for idx, role in enumerate(roles[n_canonical:], start=len(niches)):
        band = BANDS[role]
        uniform = role == NicheRole.WILDCARD      # wildcard ignores curated priors
        open_facets = set(ACTIVE_FACETS)
        chosen_principle = _reference_principle(ref_by_role, role_cursor, role)
        if chosen_principle is None:
            chosen_principle = select_principle(
                ont, space, role, open_facets, canonical_g, principle_usage,
                rng.substream("prin", idx)
            )
        overrides = principle_overrides(ont, space, chosen_principle, set())
        forbidden = _forbidden_for(ont, genotypes, antibrief, cluster_occupancy, k, role, space)

        best: tuple[float, ConceptGenotype] | None = None
        best_break: dict[str, float] = {}

        # Retry with a progressively smaller forbidden set and more candidates rather
        # than accepting a niche below D_MIN. On a tightly pruned space (a small indoor
        # site) the first pass often cannot clear the floor, and silently accepting a
        # too-close niche costs a curriculum slot later in portfolio selection.
        for attempt in range(3):
            if attempt:
                forbidden = set(sorted(forbidden)[: max(0, len(forbidden) - 4 * attempt)])
            n_cands = CANDIDATES.get(role, 90) * (1 + attempt)
            for cnd in range(n_cands):
                sub = rng.substream("cand", idx, attempt, cnd)
                try:
                    g = solve_genotype(
                        ont, space, sub,
                        forbidden=forbidden, domain_override=overrides,
                        cliche_values=cliche_values,
                        cliche_bonus=0.0 if role == NicheRole.WILDCARD else -0.6,
                        uniform=uniform, max_attempts=3,
                    )
                except SolveFailed:
                    continue
                if _quota_exceeded(g, antibrief, cluster_occupancy, k):
                    continue
                d_min = min(genotype_distance(ont, g, o) for o in genotypes)
                if d_min < D_MIN:
                    continue                      # R-ALLOC-03: the floor is an invariant
                d_canon = genotype_distance(ont, g, canonical_g)
                breakdown = {
                    "separation": round(d_min, 4),
                    "band_fit": round(band_fit(d_canon, band), 4),
                    "novelty": round(novelty(ont, g, archive), 4),
                    "incoherence": round(incoherence_prior(
                        ont, {f: g.facet_value(f) or "" for f in ACTIVE_FACETS}), 4),
                    "cliche": round(cliche_overlap(g, antibrief), 4),
                    "role_bonus": round(_role_bonus(ont, g, role, canonical_g, chosen_principle), 4),
                }
                score = (
                    1.00 * breakdown["separation"]
                    + 0.60 * breakdown["band_fit"]
                    + 0.30 * breakdown["novelty"]
                    - 0.80 * breakdown["incoherence"]
                    - 0.50 * breakdown["cliche"]
                    + 0.40 * breakdown["role_bonus"]
                )
                if best is None or score > best[0]:
                    best = (score, g)
                    best_break = {**breakdown, "score": round(score, 4),
                                  "d_canonical": round(d_canon, 4), "attempt": attempt}
            if best is not None:
                break

        if best is None:
            degraded.append(f"niche_{idx}_{role.value.lower()}_unplaceable")
            continue
        g = best[1]
        genotypes.append(g)
        principles.append(chosen_principle)
        if chosen_principle:
            principle_usage[chosen_principle.id] = principle_usage.get(chosen_principle.id, 0) + 1
        for cid in _cluster_hits(g, antibrief):
            cluster_occupancy[cid] = cluster_occupancy.get(cid, 0) + 1
        niches.append(Niche(
            niche_id=deterministic_id("nc", exploration_id, idx), exploration_id=exploration_id,
            index=idx, role=role, skeleton=PartialGenotype(),
            forbidden=sorted(forbidden), injected_principles=[chosen_principle.id] if chosen_principle else [],
            target_band=band, distance_to_canonical=best_break.get("d_canonical", 0.0),
            allocation_rank=idx, seed=seed, domain_override=overrides,
            score_breakdown=best_break,
        ))

    return Allocation(niches=niches, genotypes=genotypes, principles=principles, degraded=degraded)


def _reference_principle(ref_by_role: dict, cursor: dict, role: NicheRole):
    """R-REF-03: WILDCARD is absent from every assignment, so it can never draw one."""
    if role is NicheRole.WILDCARD:
        return None
    pool = ref_by_role.get(role.value) or []
    if not pool:
        return None
    i = cursor.get(role.value, 0)
    cursor[role.value] = i + 1
    return pool[i % len(pool)]


def _forbidden_for(
    ont: Ontology, chosen: list[ConceptGenotype], antibrief: AntiBrief,
    occupancy: dict[str, int], k: int, role: NicheRole,
    space: CreativeSearchSpace | None = None,
) -> set[str]:
    """Machine-derived 'do not go here', far more effective than 'be different'."""
    if role == NicheRole.WILDCARD:
        return set()                       # the wildcard inherits no constraints
    forbidden: set[str] = set()
    for facet in TOP_WEIGHTED_FACETS:
        used: list[str] = []
        for g in chosen:                   # most recent last
            v = g.facet_value(facet)
            if v and v not in used:
                used.append(v)
        domain_size = len(space.legal(facet)) if space else len(used)
        # never forbid so much that the domain cannot be sampled: keep >= 40% (min 3)
        keep_legal = max(3, int(domain_size * 0.4))
        allowed_to_forbid = max(0, domain_size - keep_legal)
        forbidden |= set(used[-allowed_to_forbid:]) if allowed_to_forbid else set()
    quota = max(1, k // 5)
    for c in antibrief.cliche_clusters:
        if occupancy.get(c.cluster_id, 0) >= quota:
            forbidden |= set(c.facet_values)
    return forbidden


def _quota_exceeded(g: ConceptGenotype, antibrief: AntiBrief, occupancy: dict[str, int], k: int) -> bool:
    """At most 2 of 10 concepts may match >=2 values from one cliché cluster,
    and the canonical is one of them."""
    quota = max(1, k // 5)
    refs = set(g.all_refs())
    for c in antibrief.cliche_clusters:
        if len(refs & set(c.facet_values)) >= 2 and occupancy.get(c.cluster_id, 0) >= quota:
            return True
    return False
