"""Search failure degrades the feature, never the exploration."""
from datetime import date

import pytest

from app.creative.program import build_program
from app.domain.brief import DesignBrief
from app.domain.trend import TrendDiscoveryRequest, TrendDomain, TrendMode
from app.ontology.graph import load_ontology
from app.providers.trend.search_backend import (
    FailingSearchBackend, RecordedSearchBackend, SearchError, SearchResult,
)
from app.providers.trend.web import WebSearchTrendProvider
from app.trends.service import TrendService

TODAY = date(2026, 8, 24)


def setup():
    ont = load_ontology("v1")
    brief = DesignBrief(brief_id="bf_f", raw_text="An experimental exhibition pavilion.")
    return ont, brief, build_program(ont, brief)


def test_every_domain_failing_reports_unavailable_and_raises_nothing():
    ont, brief, program = setup()
    svc = TrendService(ont, WebSearchTrendProvider(FailingSearchBackend(), today=TODAY))
    result = svc.discover(program, brief.raw_text,
                          TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS), TODAY)
    assert result.unavailable is True
    assert "TREND_DISCOVERY_UNAVAILABLE" in result.notes
    assert result.candidates == [] and result.selected_ids == []
    assert len(result.failed_domains) == len(result.plan)


class _PartialBackend:
    """Fails only for architecture-shaped queries; everything else is served."""
    name, is_live = "partial", False

    def __init__(self):
        self.inner = RecordedSearchBackend()

    def is_configured(self):
        return True

    def search(self, query, *, limit=8, region=None):
        if "architecture" in query.lower():
            raise SearchError("simulated outage")
        return self.inner.search(query, limit=limit, region=region)


def test_one_domain_failing_does_not_cost_the_others():
    ont = load_ontology("v1")
    # a brief whose other domains the recorded corpus actually covers
    brief = DesignBrief(brief_id="bf_r",
                        raw_text="A futuristic restaurant interior for 60 covers.")
    program = build_program(ont, brief)
    svc = TrendService(ont, WebSearchTrendProvider(_PartialBackend(), today=TODAY))
    result = svc.discover(program, brief.raw_text,
                          TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS), TODAY)
    assert result.unavailable is False, "one domain down is not an outage"
    assert any("ARCHITECTURE" in f for f in result.failed_domains)
    assert result.candidates, "non-failing domains must still produce candidates"


def test_a_single_failing_query_inside_a_domain_is_survivable():
    class _OneBad(_PartialBackend):
        def search(self, query, *, limit=8, region=None):
            if "materials" in query.lower():
                raise SearchError("one bad query")
            return self.inner.search(query, limit=limit, region=region)

    p = WebSearchTrendProvider(_OneBad(), today=TODAY)
    got = p.discover(queries=["2026 architecture design trends materials",
                              "2026 architecture design trends"],
                     domain=TrendDomain.ARCHITECTURE, limit=3)
    assert got, "the surviving query must still produce candidates"


def test_total_failure_inside_one_domain_is_distinguishable_from_no_results():
    p = WebSearchTrendProvider(FailingSearchBackend(), today=TODAY)
    with pytest.raises(SearchError):
        p.discover(queries=["a"], domain=TrendDomain.ART)


def test_an_exploration_is_never_failed_by_trend_discovery():
    """The pipeline takes injection=None when discovery yields nothing."""
    ont, brief, program = setup()
    svc = TrendService(ont, WebSearchTrendProvider(FailingSearchBackend(), today=TODAY))
    result = svc.discover(program, brief.raw_text,
                          TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS), TODAY)
    assert svc.injection_for(result) is None
