"""The live provider must satisfy the SAME protocol as the mock, and must never claim
to be live when it is not. No test in this file touches the network."""
from datetime import date

import pytest

from app.core.config import Settings
from app.composition import build_trend_provider
from app.domain.trend import TrendDomain
from app.providers.trend.mock import MockTrendProvider
from app.providers.trend.search_backend import (
    FailingSearchBackend, NullSearchBackend, RecordedSearchBackend, SearchError,
)
from app.providers.trend.web import WebSearchTrendProvider

TODAY = date(2026, 8, 24)


def live():
    return WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)


def test_exposes_the_same_surface_as_the_mock():
    for attr in ("name", "is_live", "is_configured", "domains_available", "discover"):
        assert hasattr(live(), attr), attr
        assert hasattr(MockTrendProvider(), attr), attr


def test_mock_and_live_are_distinguishable_and_neither_lies():
    m, w = MockTrendProvider(), live()
    assert m.is_mock is True and m.is_live is False
    # a recorded transport is NOT live, even though its evidence is real
    assert w.is_mock is False and w.is_live is False


def test_web_provider_without_a_key_is_live_but_not_configured():
    p = build_trend_provider(Settings(trend_provider="web", search_backend="brave"))
    assert p.is_live is True
    assert p.is_configured() is False        # must not silently fall back to fixtures


def test_unconfigured_backend_raises_rather_than_returning_fake_results():
    p = WebSearchTrendProvider(NullSearchBackend(), today=TODAY)
    assert p.discover(queries=["anything"], domain=TrendDomain.ART) == []


def test_every_query_failing_raises_so_the_caller_can_tell_outage_from_empty():
    p = WebSearchTrendProvider(FailingSearchBackend(), today=TODAY)
    with pytest.raises(SearchError):
        p.discover(queries=["a", "b"], domain=TrendDomain.ART)


def test_candidates_from_the_live_provider_are_never_marked_mock():
    got = live().discover(queries=["2026 architecture design trends materials"],
                          domain=TrendDomain.ARCHITECTURE, limit=3)
    assert got, "recorded corpus should answer this query"
    assert all(c.is_mock is False for c in got)
    assert all(all(e.is_mock is False for e in c.evidence) for c in got)


def test_discovery_is_deterministic_for_the_same_corpus():
    a = live().discover(queries=["2026 architecture design trends materials"],
                        domain=TrendDomain.ARCHITECTURE, limit=3)
    b = live().discover(queries=["2026 architecture design trends materials"],
                        domain=TrendDomain.ARCHITECTURE, limit=3)
    assert [c.candidate_id for c in a] == [c.candidate_id for c in b]
