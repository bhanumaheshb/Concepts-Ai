"""Independence is counted after collapsing. One story on five hosts is one signal."""
from datetime import date

from app.domain.trend import SourceTier, TrendDomain
from app.providers.trend.extraction import collapse_syndication, independent_sources, to_evidence
from app.providers.trend.search_backend import RecordedSearchBackend, SearchResult
from app.providers.trend.web import WebSearchTrendProvider

TODAY = date(2026, 8, 24)


def ev(title, url, snippet="Designers are using layered timber and soft light."):
    e, _ = to_evidence(SearchResult(title=title, url=url, snippet=snippet))
    return e


def test_two_pages_on_one_publisher_are_one_source():
    items = [ev("Timber A", "https://dezeen.com/a"), ev("Concrete B", "https://dezeen.com/b")]
    assert independent_sources(items) == 1


def test_distinct_publishers_count_separately():
    items = [ev("Timber A", "https://dezeen.com/a"), ev("Concrete B", "https://domus.com/b")]
    assert independent_sources(items) == 2


def test_a_syndicated_copy_is_not_independent_evidence():
    body = "The pavilion is built from demountable timber frames that are reused each year."
    items = [ev("Demountable Timber Pavilion Reuses Its Frame", "https://dezeen.com/a", body),
             ev("Demountable Timber Pavilion Reuses Its Frame", "https://syndicated.net/x", body)]
    kept, notes = collapse_syndication(items)
    assert len(kept) == 1
    assert independent_sources(kept) == 1


def test_genuinely_different_stories_are_kept_apart():
    a = ev("Timber Frames Return", "https://dezeen.com/a", "Timber frames are back.")
    b = ev("Colour Blocking In Retail", "https://domus.com/b", "Retail uses colour blocks.")
    kept, _ = collapse_syndication([a, b])
    assert len(kept) == 2


def test_a_demoted_source_cannot_stand_alone_as_a_candidate():
    p = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    lone = [SearchResult(title="AI Generated Trend Roundup 2026",
                         url="https://contenthub-ai.example/x",
                         snippet="Everything about design in 2026.")]
    from app.providers.trend.web import _Cluster
    assert p._to_candidate(_Cluster(lone, "ai generated"), TrendDomain.ART, ["q"], TODAY) is None
    assert p.rejected and "single demoted source" in p.rejected[0]["reason"]


def test_corroboration_reported_by_the_provider_matches_distinct_hosts():
    p = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    for c in p.discover(queries=["2026 architecture design trends materials"],
                        domain=TrendDomain.ARCHITECTURE, limit=3):
        hosts = {e.canonical_url.split("/")[2] for e in c.evidence if e.canonical_url}
        assert c.independent_sources == len(hosts)
