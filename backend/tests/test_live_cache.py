"""Caching: one exploration never issues the same query twice, and the cache never
converts a failure into a cached success."""
from datetime import date

from app.domain.brief import DesignBrief
from app.domain.trend import TrendDiscoveryRequest, TrendMode
from app.creative.program import build_program
from app.ontology.graph import load_ontology
from app.providers.trend.search_backend import RecordedSearchBackend
from app.providers.trend.web import WebSearchTrendProvider
from app.trends.service import TrendCache, TrendService

TODAY = date(2026, 8, 24)


def setup():
    ont = load_ontology("v1")
    brief = DesignBrief(brief_id="bf_c", raw_text="A futuristic restaurant interior for 60 covers.")
    return ont, brief, build_program(ont, brief)


def test_a_second_identical_discovery_issues_no_new_searches():
    ont, brief, program = setup()
    provider = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    svc = TrendService(ont, provider, TrendCache())
    req = TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS, seed=11)

    first = svc.discover(program, brief.raw_text, req, TODAY)
    calls_after_first = provider.search_calls
    second = svc.discover(program, brief.raw_text, req, TODAY)

    assert calls_after_first > 0
    assert provider.search_calls == calls_after_first     # no new network work
    assert second.search_calls == 0
    assert second.cached_queries
    assert [c.candidate_id for c in first.candidates] == \
           [c.candidate_id for c in second.candidates]


def test_a_different_mode_is_a_different_cache_key():
    ont, brief, program = setup()
    provider = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    svc = TrendService(ont, provider, TrendCache())
    svc.discover(program, brief.raw_text,
                 TrendDiscoveryRequest(mode=TrendMode.DESIGN_TRENDS, seed=11), TODAY)
    before = provider.search_calls
    svc.discover(program, brief.raw_text,
                 TrendDiscoveryRequest(mode=TrendMode.TRENDING_NOW, seed=11), TODAY)
    assert provider.search_calls > before


def test_an_expired_entry_is_not_served():
    cache = TrendCache(ttl=0.0)
    cache.put("k", [])
    assert cache.get("k") is None


def test_cache_key_is_stable_under_whitespace_and_case():
    a = TrendCache.key("2026  Design Trends", "Berlin", TrendMode.DESIGN_TRENDS, TODAY)
    b = TrendCache.key("2026 design trends", "berlin", TrendMode.DESIGN_TRENDS, TODAY)
    assert a == b
