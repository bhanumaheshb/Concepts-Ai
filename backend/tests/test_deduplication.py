"""Deduplication by canonical URL, normalised title, and syndication."""
from app.providers.trend.extraction import collapse_syndication, to_evidence
from app.providers.trend.search_backend import SearchResult


def ev(title, url, snippet="Layered timber and diffuse light across the whole room."):
    e, _ = to_evidence(SearchResult(title=title, url=url, snippet=snippet))
    return e


def test_the_same_url_with_different_tracking_params_is_one_item():
    a = ev("Timber", "https://dezeen.com/a?utm_source=news")
    b = ev("Timber", "https://www.dezeen.com/a/?utm_campaign=x")
    kept, _ = collapse_syndication([a, b])
    assert len(kept) == 1


def test_near_identical_titles_collapse():
    a = ev("The Top 10 Timber Pavilions of 2026", "https://dezeen.com/a")
    b = ev("Top 10 Timber Pavilions for 2026", "https://domus.com/b")
    kept, _ = collapse_syndication([a, b])
    assert len(kept) == 1


def test_syndication_across_hosts_is_recorded_as_such():
    body = "The pavilion uses demountable timber frames reused every season."
    a = ev("Demountable Timber Pavilion Reuses Frames Each Season", "https://dezeen.com/a", body)
    b = ev("Demountable Timber Pavilion Reuses Frames Every Season", "https://reprint.net/x", body)
    kept, notes = collapse_syndication([a, b])
    assert len(kept) == 1
    assert any("syndication" in n for n in notes)


def test_distinct_coverage_of_the_same_topic_is_not_collapsed():
    a = ev("Timber Frames Return To Public Buildings", "https://dezeen.com/a",
           "Public buildings are returning to exposed timber frames.")
    b = ev("Why Architects Are Rediscovering Rammed Earth", "https://domus.com/b",
           "Rammed earth walls are being used for thermal mass.")
    kept, _ = collapse_syndication([a, b])
    assert len(kept) == 2


def test_collapsing_is_order_independent_in_count():
    items = [ev("Timber A", "https://dezeen.com/a"),
             ev("Timber A", "https://reprint.net/a"),
             ev("Rammed Earth Walls Return", "https://domus.com/c", "Rammed earth is back.")]
    assert len(collapse_syndication(items)[0]) == len(collapse_syndication(items[::-1])[0])
