"""Freshness rests on dated evidence. Undated evidence is never called recent."""
from datetime import date, timedelta

from app.domain.trend import TrendDomain, TrendFreshness
from app.providers.trend.search_backend import RecordedSearchBackend, SearchResult
from app.providers.trend.web import WebSearchTrendProvider, _Cluster, _recency
from app.providers.trend.extraction import to_evidence
from app.trends.scoring import classify_freshness

TODAY = date(2026, 8, 24)


def ev(published, url="https://dezeen.com/a"):
    e, _ = to_evidence(SearchResult(title="T", url=url, snippet="s", published=published))
    return e


def test_no_dated_evidence_gives_zero_recency_and_zero_confidence():
    recency, confidence, urls = _recency([ev(None)], TODAY)
    assert (recency, confidence, urls) == (0.0, 0.0, [])


def test_confidence_is_the_fraction_of_evidence_that_is_actually_dated():
    _, confidence, _ = _recency([ev(TODAY), ev(None), ev(None), ev(None)], TODAY)
    assert confidence == 0.25


def test_recency_falls_with_age_and_never_goes_negative():
    fresh, _, _ = _recency([ev(TODAY - timedelta(days=10))], TODAY)
    old, _, _ = _recency([ev(TODAY - timedelta(days=400))], TODAY)
    ancient, _, _ = _recency([ev(TODAY - timedelta(days=5000))], TODAY)
    assert fresh > old > 0.0
    assert ancient == 0.0


def test_an_undated_candidate_is_flagged_low_confidence_not_called_current():
    p = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    rows = [SearchResult(title="Layered Light In Restaurants",
                         url="https://frameweb.com/a",
                         snippet="Restaurants layer light across timber and stone."),
            SearchResult(title="Layered Light Elsewhere", url="https://domus.com/b",
                         snippet="Another view on layered light and stone surfaces.")]
    c = p._to_candidate(_Cluster(rows, "layered light"), TrendDomain.HOSPITALITY, ["q"], TODAY)
    assert c is not None
    assert c.freshness_confidence == 0.0
    assert c.low_confidence is True
    assert "no dated evidence" in c.rejected_reason


def test_a_2019_article_cannot_be_classified_as_trending_now():
    p = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    old = date(2019, 4, 1)
    rows = [SearchResult(title="Old Story", url="https://dezeen.com/a", snippet="s", published=old),
            SearchResult(title="Old Story Two", url="https://domus.com/b", snippet="t", published=old)]
    c = p._to_candidate(_Cluster(rows, "old story"), TrendDomain.ARCHITECTURE, ["q"], TODAY)
    assert classify_freshness(c, TODAY) in (TrendFreshness.DECLINING, TrendFreshness.ESTABLISHED,
                                            TrendFreshness.EVERGREEN)


def test_momentum_requires_two_independent_recent_sources():
    p = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    recent = TODAY - timedelta(days=30)
    # deliberately DIFFERENT stories: two near-identical snippets on two hosts would be
    # collapsed as syndication, which is the behaviour test_source_independence covers.
    one = [SearchResult(title="Cast Glass Blocks Return To Galleries",
                        url="https://dezeen.com/a",
                        snippet="Galleries are casting glass blocks into thick walls.",
                        published=recent)]
    two = one + [SearchResult(title="Glass Masonry In Public Rooms",
                              url="https://domus.com/b",
                              snippet="Public rooms stack translucent masonry to diffuse light.",
                              published=recent)]
    c1 = p._to_candidate(_Cluster(one, "signal"), TrendDomain.ART, ["q"], TODAY)
    c2 = p._to_candidate(_Cluster(two, "signal"), TrendDomain.ART, ["q"], TODAY)
    assert c1.signal.momentum == 0.0
    assert c2.signal.momentum > 0.0
