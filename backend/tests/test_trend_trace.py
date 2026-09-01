"""The trace must let a reader reconstruct every claim back to a retrieved source, and
must never let mock, recorded and live be confused."""
from datetime import date

from app.core.config import Settings
from app.composition import build_trend_provider
from app.creative.program import build_program
from app.domain.brief import DesignBrief
from app.domain.trend import TrendDiscoveryRequest, TrendMode
from app.ontology.graph import load_ontology
from app.providers.trend.search_backend import RecordedSearchBackend
from app.providers.trend.web import WebSearchTrendProvider
from app.trends.service import TrendService

TODAY = date(2026, 8, 24)


def run(provider):
    ont = load_ontology("v1")
    brief = DesignBrief(brief_id="bf_t", raw_text="A futuristic restaurant interior for 60 covers.")
    svc = TrendService(ont, provider)
    return svc.discover(build_program(ont, brief), brief.raw_text,
                        TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS, max_candidates=12),
                        TODAY)


def test_the_result_reports_query_count_and_search_calls():
    provider = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    r = run(provider)
    assert r.queries and r.search_calls > 0
    assert r.raw_results == len(r.candidates)


def test_every_candidate_carries_at_least_one_source_with_a_url():
    r = run(WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY))
    for c in r.candidates:
        assert c.evidence
        assert any(e.url for e in c.evidence)
        assert all(e.retrieved_at is not None for e in c.evidence)


def test_rejected_candidates_state_a_reason():
    r = run(WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY))
    for entry in r.rejected:
        assert ":" in entry and entry.split(":", 1)[1].strip()


def test_the_three_evidence_modes_are_never_conflated():
    mock = run(build_trend_provider(Settings(trend_provider="mock")))
    rec = run(build_trend_provider(Settings(trend_provider="recorded")))
    assert mock.is_mock is True and "MOCK TREND DATA" in mock.notes
    assert rec.is_mock is False
    assert "RECORDED EVIDENCE" in rec.notes
    assert "MOCK" not in rec.notes.upper().replace("RECORDED", "")


def test_a_recorded_run_never_claims_to_be_live():
    provider = build_trend_provider(Settings(trend_provider="recorded"))
    assert provider.is_live is False
    notes = run(provider).notes.lower()
    # the note may (and does) mention liveness in order to DENY it
    assert "not a live search" in notes
    assert "live discovery" not in notes and "live search results" not in notes


def test_design_value_is_always_accompanied_by_its_reason():
    r = run(WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY))
    for c in r.candidates:
        assert c.design_value_reason
        if c.design_value_estimate is None:
            assert c.design_value_uncertain is True
