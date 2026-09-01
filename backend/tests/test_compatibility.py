"""Classification by the ontology's own typed edges."""
from app.domain.reference import CompatibilityClass
from app.references.compatibility import classify


def test_single_reference_is_trivially_compatible(ont, fixtures):
    r = classify(ont, [fixtures["ref_bridgerton"]])
    assert r.verdict is CompatibilityClass.COMPATIBLE


def test_spec_examples_classify_as_specified(ont, fixtures):
    # "Regency + Indian courtyard -> COMPATIBLE"
    a = classify(ont, [fixtures["ref_palace_architecture"], fixtures["ref_bridgerton"]])
    assert a.verdict is CompatibilityClass.COMPATIBLE
    # "Regency + brutalism -> INTERESTING TENSION", licensed by a tensions_with edge
    b = classify(ont, [fixtures["ref_brutalism"], fixtures["ref_bridgerton"]])
    assert b.verdict is CompatibilityClass.INTERESTING_TENSION
    assert any(c.edge == "tensions_with" for c in b.conflicts)


def test_no_combination_ever_returns_an_error(ont, fixtures):
    """R-REF-13 — every pair classifies; none raises."""
    ids = sorted(fixtures)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            r = classify(ont, [fixtures[a], fixtures[b]])
            assert r.verdict in set(CompatibilityClass)
            assert r.rationale


def test_high_risk_caps_influence(ont, fixtures):
    for i, a in enumerate(sorted(fixtures)):
        for b in sorted(fixtures)[i + 1:]:
            r = classify(ont, [fixtures[a], fixtures[b]])
            if r.verdict in (CompatibilityClass.HIGH_RISK, CompatibilityClass.INCOHERENT):
                assert r.influence_cap == 0.6


def test_three_references_still_classify(ont, fixtures):
    r = classify(ont, [fixtures["ref_bridgerton"], fixtures["ref_stepwell"],
                       fixtures["ref_brutalism"]])
    assert r.verdict in set(CompatibilityClass)
    assert len(r.reference_ids) == 3
