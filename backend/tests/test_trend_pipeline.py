"""Trend → Reference Intelligence → Divergence Engine, and the OFF regression."""
from collections import Counter

import pytest

from app.core.hashing import sha256_of
from app.creative.pipeline import Pipeline
from app.creative.program import build_program
from app.diversity.metric import D_MIN
from app.domain.brief import DesignBrief
from app.domain.trend import TrendDiscoveryRequest, TrendDomain as D, TrendMode
from app.persistence.repository import InMemoryStore
from app.space.instantiate import instantiate_with_relaxation
from app.trends.reference import candidate_to_dna

TARGET = {"CANONICAL": 1, "ADJACENT": 3, "EXPLORATORY": 4, "RADICAL": 1, "WILDCARD": 1}
SANGEETH = "Luxury high-energy Sangeeth for 500 guests"


def _setup(ont, text=SANGEETH, loc="Jaipur, May"):
    brief = DesignBrief(brief_id=f"bf_tr_{abs(hash(text)) % 9999}", raw_text=text, location=loc)
    program = build_program(ont, brief)
    return brief, program, instantiate_with_relaxation(ont, program)


def _explore(container, ont, trend_service, text, mode, seed=42, custom=None, loc="Jaipur, May"):
    brief, program, space = _setup(ont, text, loc)
    req = TrendDiscoveryRequest(mode=mode, domains=custom or [], max_selected=3,
                                region=loc, seed=seed)
    result = trend_service.discover(program, text, req)
    injection = trend_service.injection_for(result, influence=0.55, space=space, seed=seed)
    rec = container.pipeline.run(brief, k=10, seed=seed, injection=injection,
                                 trend_result=result)
    return rec, result, injection


# ── THE critical regression ──────────────────────────────────────

def test_trend_off_is_byte_identical(container, ont):
    """Mode OFF performs no discovery and cannot alter a single genotype."""
    def genotypes(pipeline):
        rec = pipeline.run(DesignBrief(
            brief_id="bf_off", raw_text="Create a luxury Indian wedding mandap for 500 guests.",
            location="Jaipur, May"), k=10, seed=42)
        return sha256_of([c.genotype.model_dump(mode="json") for c in rec.concepts])

    a = genotypes(Pipeline(ont, container.llm, InMemoryStore(),
                           use_llm_critics=container.pipeline.use_llm_critics))
    b = genotypes(Pipeline(ont, container.llm, InMemoryStore(),
                           use_llm_critics=container.pipeline.use_llm_critics))
    assert a == b
    assert TrendDiscoveryRequest(mode=TrendMode.OFF).enabled is False


def test_off_mode_builds_nothing(container, ont, trend_service):
    rec = container.pipeline.run(
        DesignBrief(brief_id="bf_off2", raw_text=SANGEETH, location="Jaipur"), k=10, seed=42)
    assert rec.trend_result is None
    assert rec.injection is None
    assert all(c.reference_context is None for c in rec.concepts)


# ── trend → ReferenceDNA → injection ─────────────────────────────

def test_candidate_becomes_a_valid_reference_dna(ont, trend_provider):
    for domain in trend_provider.domains_available():
        for c in trend_provider.discover(queries=[], domain=domain, limit=3):
            dna = candidate_to_dna(ont, c)
            assert len(dna.traits) >= 6
            assert len(dna.literal_reading.facet_values) >= 2
            assert dna.literal_reading.naive_rendering
            for t in dna.traits:
                for s in t.suggests:
                    assert s in ont.nodes


def test_trend_injection_uses_the_existing_machinery(ont, trend_service):
    _, program, space = _setup(ont)
    result = trend_service.discover(program, SANGEETH,
                                    TrendDiscoveryRequest(mode=TrendMode.SURPRISE_ME, seed=42))
    inj = trend_service.injection_for(result, space=space, seed=42)
    assert inj is not None
    assert inj.principles
    assert inj.cliche_clusters and all(cl.evidence == "REFERENCE" for cl in inj.cliche_clusters)
    assert inj.influence.max_biased_facets <= 3
    from app.domain.common import NicheRole
    assert NicheRole.WILDCARD not in inj.influence.role_coverage


# ── the six benchmark cases ──────────────────────────────────────

@pytest.mark.parametrize("mode", [
    TrendMode.CURRENT_INSPIRATION, TrendMode.TRENDING_NOW,
    TrendMode.DESIGN_TRENDS, TrendMode.CULTURAL_MOMENT, TrendMode.SURPRISE_ME,
])
def test_every_mode_still_produces_a_valid_portfolio(container, ont, trend_service, mode):
    rec, result, inj = _explore(container, ont, trend_service, SANGEETH, mode)
    assert rec.status == "COMPLETE", rec.error
    assert len(rec.concepts) == 10
    assert Counter(c.role.value for c in rec.concepts) == TARGET
    assert rec.matrix.min_pairwise >= D_MIN
    assert rec.matrix.vendi_score >= 6.5
    assert all(c.evaluation.gate_passed for c in rec.concepts)
    assert all(c.reference_context.surface_leaks == [] for c in rec.concepts)


def test_case5_different_brief_discovers_different_domains(container, ont, trend_service):
    _, sangeeth, _ = _setup(ont, SANGEETH)
    _, resto, _ = _setup(ont, "A futuristic restaurant interior for 60 covers", "Mumbai")
    req = TrendDiscoveryRequest(mode=TrendMode.SURPRISE_ME, seed=42)
    a = {p.domain for p in trend_service.discover(sangeeth, SANGEETH, req).plan}
    b = {p.domain for p in trend_service.discover(
        resto, "A futuristic restaurant interior for 60 covers", req).plan}
    assert a != b


def test_case6_custom_restricts_to_the_chosen_domains(container, ont, trend_service):
    custom = [D.ARCHITECTURE, D.FASHION, D.TECHNOLOGY]
    _, program, _ = _setup(ont, "A luxury retail flagship store", "London")
    result = trend_service.discover(
        program, "A luxury retail flagship store",
        TrendDiscoveryRequest(mode=TrendMode.CUSTOM, domains=custom, seed=42))
    assert [p.domain for p in result.plan] == custom
    assert {c.domain for c in result.candidates} <= set(custom)


def test_surprise_me_reaches_more_than_one_domain(container, ont, trend_service):
    _, program, _ = _setup(ont, "Create a crazy Sangeeth concept")
    result = trend_service.discover(
        program, "Create a crazy Sangeeth concept",
        TrendDiscoveryRequest(mode=TrendMode.SURPRISE_ME, max_selected=3, seed=42))
    assert len(result.domain_spread()) >= 2, "SURPRISE_ME returned a single-domain set"


# ── transformation: a current signal is abstracted, not copied ───

def test_trend_concepts_are_transformed_not_copied(container, ont, trend_service):
    rec, result, _ = _explore(container, ont, trend_service, SANGEETH,
                              TrendMode.CURRENT_INSPIRATION)
    ctxs = [c.reference_context for c in rec.concepts]
    mean_t = sum(c.transformation for c in ctxs) / len(ctxs)
    assert mean_t >= 0.60, f"mean transformation {mean_t:.3f}"
    # no discovered signal's naive rendering survives into a concept
    for cand in result.selected():
        words = {w for w in cand.naive_rendering.lower().split() if len(w) > 6}
        for c in rec.concepts:
            thesis = c.phenotype.design_thesis.lower()
            overlap = sum(1 for w in words if w in thesis)
            assert overlap < max(3, len(words) // 3), \
                f"{c.phenotype.title} reproduces the naive rendering"


# ── caching + provider independence ──────────────────────────────

def test_queries_are_cached_within_a_session(ont, trend_service):
    _, program, _ = _setup(ont)
    req = TrendDiscoveryRequest(mode=TrendMode.CURRENT_INSPIRATION, seed=42)
    trend_service.discover(program, SANGEETH, req)
    misses = trend_service.cache.misses
    trend_service.discover(program, SANGEETH, req)
    assert trend_service.cache.hits > 0
    assert trend_service.cache.misses == misses, "the same queries were re-issued"


def test_the_service_only_knows_the_protocol(ont):
    """Provider independence: a stub with the right shape works unchanged."""
    from app.trends.service import TrendService

    class StubProvider:
        name = "stub"
        is_live = True

        def is_configured(self):
            return True

        def domains_available(self):
            return []

        def discover(self, *, queries, domain, limit, seed=0):
            return []

    _, program, _ = _setup(ont)
    result = TrendService(ont, StubProvider()).discover(
        program, SANGEETH, TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS, seed=1))
    assert result.provider == "stub" and result.is_mock is False
    assert result.candidates == [] and result.selected_ids == []


def test_mock_data_is_clearly_marked(ont, trend_service):
    _, program, _ = _setup(ont)
    result = trend_service.discover(
        program, SANGEETH, TrendDiscoveryRequest(mode=TrendMode.CURRENT_INSPIRATION, seed=42))
    assert result.is_mock and "MOCK TREND DATA" in result.notes
    for c in result.candidates:
        assert c.is_mock
        assert all("MOCK" in e.source.upper() for e in c.evidence)


def test_every_cliche_evidence_kind_has_a_merge_weight():
    """A missing weight only fails when two clusters actually merge, so it hid until a
    discovered trend's literal reading overlapped a curated cliché."""
    import typing
    from app.creative.antibrief import SOURCE_WEIGHT
    from app.domain.antibrief import ClicheCluster
    kinds = typing.get_args(ClicheCluster.model_fields["evidence"].annotation)
    assert set(kinds) <= set(SOURCE_WEIGHT), \
        f"no merge weight for {set(kinds) - set(SOURCE_WEIGHT)}"
