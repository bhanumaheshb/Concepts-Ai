"""Every band, and the three invariants that hold at all of them."""
import pytest

from app.domain.common import NicheRole
from app.domain.reference import ReferencePreset, ReferenceRequest, ReferenceSelector
from app.references.influence import derive, resolve_request

BANDS = [(0.10, "trace"), (0.30, "light"), (0.55, "balanced"), (0.80, "strong"), (0.95, "maximum")]


@pytest.mark.parametrize("level,label", BANDS)
def test_each_band_resolves(level, label):
    inf = derive(level)
    assert inf.band == label
    assert inf.max_principles >= 1
    assert 1.0 <= inf.prior_multiplier <= 4.0


def test_wildcard_is_never_reached_at_any_level():
    for i in range(0, 101):
        assert NicheRole.WILDCARD not in derive(i / 100).role_coverage


def test_at_most_three_facets_are_biased_at_any_level():
    """R-REF-02 — at least nine of twelve facets always remain free."""
    for i in range(0, 101):
        assert derive(i / 100).max_biased_facets <= 3


def test_bands_are_monotonic():
    prev = derive(0.0)
    for i in range(1, 101):
        cur = derive(i / 100)
        assert cur.max_biased_facets >= prev.max_biased_facets
        assert cur.prior_multiplier >= prev.prior_multiplier
        assert len(cur.role_coverage) >= len(prev.role_coverage)
        prev = cur


def test_high_risk_cap_lowers_the_band():
    assert derive(0.95).band == "maximum"
    assert derive(0.95, influence_cap=0.6).band == "balanced"


def test_presets_are_configuration_not_code_paths():
    for preset in ReferencePreset:
        req = ReferenceRequest(references=[ReferenceSelector(query="x")], preset=preset)
        inf, dims = resolve_request(req)
        assert 0.0 <= inf.level <= 1.0
        assert NicheRole.WILDCARD not in inf.role_coverage
    arch = resolve_request(ReferenceRequest(references=[ReferenceSelector(query="x")],
                                            preset=ReferencePreset.ARCHITECTURAL))
    assert arch[0].level == 0.75 and len(arch[1]) == 5
    free = resolve_request(ReferenceRequest(references=[ReferenceSelector(query="x")],
                                            preset=ReferencePreset.FREE_INTERPRETATION))
    assert free[0].abstraction_floor == 0.85


def test_prior_bias_never_changes_the_legal_domain(ont, program, fixtures):
    """R-REF-14 — bias multiplies weights; it must not add or remove a legal value."""
    from app.references.injection import build_injection
    from app.space.instantiate import instantiate_with_relaxation
    plain = instantiate_with_relaxation(ont, program)
    inj = build_injection(ont, [fixtures["ref_brutalism"]],
                          ReferenceRequest(references=[ReferenceSelector(query="x")],
                                           influence=1.0), plain, seed=1)
    biased = instantiate_with_relaxation(ont, program, inj.prior_bias)
    for d in plain.domains:
        assert set(d.values()) == set(biased.domain(d.facet_id).values()), d.facet_id
    # ... and at least one weight went up
    changed = any(
        biased.domain(d.facet_id).legal[i].weight > d.legal[i].weight
        for d in plain.domains for i in range(len(d.legal))
    )
    assert changed, "prior bias had no effect at influence 1.0"
