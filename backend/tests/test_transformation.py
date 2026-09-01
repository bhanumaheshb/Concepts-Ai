"""T and I — deterministic, no provider call (R-REF-09)."""
import pytest

from app.core.seeded import SeededRandom
from app.domain.common import NicheRole
from app.domain.genotype import PartialGenotype
from app.genotype.solve import solve_genotype
from app.references.abstraction import principles_from
from app.references.transformation import (
    literal_genotype, literal_occupancy, naive_overlap, score_concept, surface_leaks,
)


def _principles(fixtures, space, rid="ref_bridgerton"):
    ps, _ = principles_from(fixtures[rid], space, 0.6)
    return ps


def test_channels_are_all_in_range(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    ps = _principles(fixtures, space)
    g = solve_genotype(ont, space, SeededRandom(1, "t"))
    ctx = score_concept(ont, g, "a quiet stone court", "", ps, [dna], space)
    c = ctx.channels
    for v in (c.literal_occupancy, c.displacement, c.principle_abstraction,
              c.naive_overlap, c.facet_freedom, ctx.transformation, ctx.influence_measured):
        assert 0.0 <= v <= 1.0


def test_surface_leak_zeroes_the_score(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    ps = _principles(fixtures, space)
    g = solve_genotype(ont, space, SeededRandom(2, "t"))
    clean = score_concept(ont, g, "a quiet stone court", "", ps, [dna], space)
    leaked = score_concept(ont, g, "a Bridgerton ballroom", "", ps, [dna], space)
    assert clean.transformation > 0.0
    assert leaked.transformation == 0.0
    assert leaked.surface_leaks


def test_a_literal_genotype_scores_low_and_a_transformed_one_scores_high(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    ps = _principles(fixtures, space)
    lit = literal_genotype(ont, dna, space)
    assert lit is not None
    literal_ctx = score_concept(ont, lit, dna.literal_reading.naive_rendering, "", ps, [dna], space)
    assert literal_ctx.transformation < 0.45, literal_ctx.channels

    far = solve_genotype(ont, space, SeededRandom(99, "far"))
    far_ctx = score_concept(ont, far, "a sunken court of dry-stacked stone", "", ps, [dna], space)
    assert far_ctx.transformation > 0.6, far_ctx.channels


def test_scoring_is_deterministic_and_calls_no_provider(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    ps = _principles(fixtures, space)
    g = solve_genotype(ont, space, SeededRandom(5, "t"))
    a = score_concept(ont, g, "a stone court", "", ps, [dna], space)
    b = score_concept(ont, g, "a stone court", "", ps, [dna], space)
    assert a.model_dump() == b.model_dump()


def test_literal_occupancy_measures_the_obvious_answer(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    lit = literal_genotype(ont, dna, space)
    assert literal_occupancy(lit, [dna]) > 0.3
    far = solve_genotype(ont, space, SeededRandom(77, "far"))
    assert literal_occupancy(far, [dna]) <= literal_occupancy(lit, [dna])


def test_naive_overlap_catches_paraphrase(fixtures):
    dna = fixtures["ref_bridgerton"]
    assert naive_overlap(dna.literal_reading.naive_rendering, [dna]) > 0.5
    assert naive_overlap("a dry-stacked stone terrace cut into the ground", [dna]) < 0.3


def test_influence_is_zero_when_nothing_stuck(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    ps = _principles(fixtures, space)
    g = solve_genotype(ont, space, SeededRandom(3, "t"),
                       skeleton=PartialGenotype(occupation_staging="occupation_staging:frontal_stage"))
    ctx = score_concept(ont, g, "a plain room", "", [], [dna], space)
    assert ctx.influence_measured == 0.0


def test_literal_slot_reports_influence_by_occupancy(ont, fixtures, space):
    dna = fixtures["ref_bridgerton"]
    lit = literal_genotype(ont, dna, space)
    ctx = score_concept(ont, lit, "a formal court", "", [], [dna], space, is_literal_slot=True)
    assert ctx.is_literal_slot
    assert ctx.influence_measured > 0.0, "the canonical carries the reference via the cliché seed"
