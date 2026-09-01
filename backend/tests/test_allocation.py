from collections import Counter

from app.creative.antibrief import build_antibrief
from app.diversity.metric import D_MIN, genotype_distance
from app.domain.common import NicheRole
from app.niche.allocator import allocate, expand_curriculum


def _alloc(ont, space, program, seed, k=10):
    ab = build_antibrief(ont, program, space, None, seed)
    return allocate(ont, space, ab, "ex_test", k, seed)


def test_curriculum_shape():
    roles = expand_curriculum(10)
    assert Counter(roles) == {
        NicheRole.CANONICAL: 1, NicheRole.ADJACENT: 3,
        NicheRole.EXPLORATORY: 4, NicheRole.RADICAL: 1, NicheRole.WILDCARD: 1,
    }


def test_allocation_is_deterministic(ont, space, program):
    a = _alloc(ont, space, program, 42)
    b = _alloc(ont, space, program, 42)
    assert [g.model_dump() for g in a.genotypes] == [g.model_dump() for g in b.genotypes]
    assert [n.role for n in a.niches] == [n.role for n in b.niches]


def test_different_seeds_give_different_allocations(ont, space, program):
    a = _alloc(ont, space, program, 42)
    b = _alloc(ont, space, program, 777)
    assert [g.model_dump() for g in a.genotypes] != [g.model_dump() for g in b.genotypes]


def test_min_distance_invariant_holds(ont, space, program):
    """R-ALLOC-03: every allocated pair must clear the duplicate floor."""
    for seed in (42, 7, 1234, 99):
        alloc = _alloc(ont, space, program, seed)
        gs = alloc.genotypes
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                d = genotype_distance(ont, gs[i], gs[j])
                assert d >= D_MIN - 1e-9, f"seed {seed}: pair {i},{j} at {d:.3f}"


def test_canonical_is_seeded_from_the_antibrief(ont, space, program):
    ab = build_antibrief(ont, program, space, None, 42)
    alloc = allocate(ont, space, ab, "ex_c", 10, 42)
    canonical = alloc.genotypes[0]
    seeded = ab.canonical_seed.assigned()
    assert seeded, "anti-brief produced no canonical seed"
    hits = sum(1 for facet, value in seeded.items()
               if facet != "material_primary" and canonical.facet_value(facet) == value)
    assert hits >= 1, "canonical genotype ignored its seed"


def test_wildcard_carries_no_forbidden_set(ont, space, program):
    alloc = _alloc(ont, space, program, 42)
    for n in alloc.niches:
        if n.role == NicheRole.WILDCARD:
            assert n.forbidden == []


def test_allocated_genotypes_violate_no_exclusions(ont, space, program):
    for seed in (42, 7):
        for g in _alloc(ont, space, program, seed).genotypes:
            refs = g.all_refs()
            for i, a in enumerate(refs):
                for b in refs[i + 1:]:
                    assert b not in ont.excludes(a), f"{a} excludes {b}"
