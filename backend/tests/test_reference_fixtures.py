"""The six authoring rules, enforced against all eight fixtures."""
import pytest

from app.domain.reference import CONTEXT_DIMENSIONS, detect_proper_nouns
from app.references.types import LOAD_BEARING_SALIENCE, coverage_ok, profile

EXPECTED = {
    "ref_bridgerton", "ref_stranger_things", "ref_stepwell", "ref_brutalism",
    "ref_temperate_forest", "ref_speculative_technology", "ref_open_world_city",
    "ref_palace_architecture",
}


def test_all_eight_fixtures_load(fixtures):
    assert set(fixtures) == EXPECTED


def test_rule1_trait_count_and_load_bearing_coverage(fixtures):
    for rid, dna in fixtures.items():
        assert len(dna.traits) >= 6, rid
        ok, detail = coverage_ok(dna.identity.kind, dna.traits)
        assert ok, f"{rid}: R-REF-05 not met, missing any of {detail}"


def test_rule2_no_proper_noun_no_display_name_no_own_token(fixtures):
    for rid, dna in fixtures.items():
        for t in dna.traits:
            assert not detect_proper_nouns(t.statement), f"{rid}/{t.trait_id}"
            assert dna.identity.display_name.lower() not in t.statement.lower(), rid
            for tok in dna.surface_lexicon.blocked():
                assert tok not in t.statement.lower(), f"{rid}/{t.trait_id} leaks {tok!r}"


def test_rule3_every_suggests_resolves(ont, fixtures):
    for rid, dna in fixtures.items():
        for t in dna.traits:
            for s in t.suggests:
                assert s in ont.nodes, f"{rid}/{t.trait_id} -> {s}"


def test_rule4_literal_reading_is_resolvable_and_has_two_values(ont, fixtures):
    for rid, dna in fixtures.items():
        assert len(dna.literal_reading.facet_values) >= 2, rid
        for v in dna.literal_reading.facet_values:
            assert v in ont.nodes, f"{rid} -> {v}"


def test_rule5_naive_rendering_present(fixtures):
    """The author must write down the bad answer — it is the denominator of channel 5."""
    for rid, dna in fixtures.items():
        assert len(dna.literal_reading.naive_rendering.split()) >= 15, rid


def test_rule6_tokens_categorised_and_transformed_or_justified(fixtures):
    for rid, dna in fixtures.items():
        for tok in dna.surface_lexicon.tokens:
            assert tok.category, f"{rid}/{tok.token}"
            assert tok.transformed_to or tok.justification, f"{rid}/{tok.token}"


def test_context_dimensions_never_bias_a_facet(fixtures):
    for rid, dna in fixtures.items():
        for t in dna.traits:
            if t.dimension in CONTEXT_DIMENSIONS:
                assert t.maps_to == [], f"{rid}/{t.trait_id}"


def test_absent_dimension_salience_is_capped(fixtures):
    for rid, dna in fixtures.items():
        prof = profile(dna.identity.kind)
        for t in dna.traits:
            if t.dimension in prof.usually_absent:
                assert t.salience <= 0.4, f"{rid}/{t.trait_id} not capped"


def test_majority_of_tokens_carry_a_transformation(fixtures):
    for rid, dna in fixtures.items():
        toks = dna.surface_lexicon.tokens
        transformed = [t for t in toks if t.transformed_to]
        assert len(transformed) / max(1, len(toks)) >= 0.5, rid
