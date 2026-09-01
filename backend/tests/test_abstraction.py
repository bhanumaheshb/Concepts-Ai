"""The five-stage ladder: STRIP → RELATE → LIFT → MAP → VERIFY."""
from app.references.abstraction import (
    lift, map_facets, principles_from, relates, strip, verify,
)


def test_strip_removes_blocked_tokens_and_proper_nouns():
    out, removed = strip("a Bridgerton ballroom lit by candles", ["bridgerton", "ballroom"])
    assert "bridgerton" not in out.lower() and "ballroom" not in out.lower()
    assert {"bridgerton", "ballroom"} <= set(removed)


def test_relate_rejects_a_list_of_nouns_and_a_look():
    assert relates("gold and marble and mirrors") is False
    assert relates("it looks like a period drama interior") is False
    assert relates("light originates below eye level, from many small sources") is True


def test_lift_replaces_a_domain_noun_with_its_spatial_function():
    out, changed = lift("the ballroom is lit by a chandelier")
    assert changed
    assert "ballroom" not in out and "collective display" in out


def test_map_drops_facets_the_space_pruned(fixtures, space):
    dna = fixtures["ref_bridgerton"]
    trait = next(t for t in dna.traits if t.maps_to)
    facets = map_facets(trait, space)
    assert facets and all(space.legal(f) for f in facets)


def test_verify_catches_every_failure_mode(fixtures):
    dna = fixtures["ref_bridgerton"]
    assert verify("a society performs itself in public", dna) == []
    assert any("names the reference" in p for p in verify("Bridgerton is a society", dna))
    assert any("blocked token" in p for p in verify("the ballroom is looked at", dna))


def test_worked_cases_produce_transferable_statements(ont, fixtures, space):
    """The spec's own examples: none of the outputs may contain its source vocabulary."""
    cases = {
        "ref_stepwell": ["stepwell", "baori", "vav"],
        "ref_stranger_things": ["stranger things", "upside down", "demogorgon"],
        "ref_open_world_city": ["gta", "los santos"],
        "ref_bridgerton": ["bridgerton", "regency", "ballroom"],
    }
    for rid, forbidden in cases.items():
        principles, _ = principles_from(fixtures[rid], space, 0.6)
        assert principles, rid
        blob = " ".join(s for p in principles for s in p.statements).lower()
        for tok in forbidden:
            assert tok not in blob, f"{rid} leaked {tok!r}"


def test_source_domain_is_abstract_and_never_names_the_reference(ont, fixtures, space):
    for rid, dna in fixtures.items():
        principles, _ = principles_from(dna, space, 0.6)
        name = dna.identity.display_name.lower()
        for p in principles:
            assert name not in p.source_domain.lower(), f"{rid}: {p.source_domain}"
            for tok in dna.surface_lexicon.blocked():
                assert tok not in p.source_domain.lower(), f"{rid}: {p.source_domain}"


def test_every_reference_principle_carries_provenance(fixtures, space):
    principles, _ = principles_from(fixtures["ref_brutalism"], space, 0.6)
    for p in principles:
        assert p.provenance.source == "REFERENCE"
        assert p.provenance.reference_ids == ("ref_brutalism",)
        assert p.provenance.dimension
        assert p.id.startswith("refprin_")


def test_abstraction_log_records_before_and_after(fixtures, space):
    _, log = principles_from(fixtures["ref_stepwell"], space, 0.6)
    assert log
    assert all(r.raw and r.steps_applied for r in log)
