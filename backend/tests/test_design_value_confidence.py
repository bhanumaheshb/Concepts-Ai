"""Design value is estimated transparently or not at all. No invented number."""
from datetime import date

from app.domain.trend import TrendDomain
from app.providers.trend.design_value import MIN_CONFIDENCE, estimate_design_value
from app.providers.trend.extraction import to_evidence
from app.providers.trend.search_backend import RecordedSearchBackend, SearchResult
from app.providers.trend.web import WebSearchTrendProvider

TODAY = date(2026, 8, 24)


def ev(title, snippet, url="https://dezeen.com/a"):
    e, _ = to_evidence(SearchResult(title=title, url=url, snippet=snippet))
    return e


def test_no_evidence_gives_no_number():
    est = estimate_design_value([], TrendDomain.ART)
    assert est.estimate is None and est.uncertain is True


def test_thin_evidence_is_uncertain_rather_than_guessed():
    est = estimate_design_value([ev("X", "ok")], TrendDomain.ART)
    assert est.estimate is None
    assert est.uncertain is True
    assert "DESIGN_VALUE_UNCERTAIN" in est.reason


def test_a_spatially_rich_source_scores_above_a_commercial_one():
    rich = [ev("Layered Light", "Designers shape light across timber, stone and plaster "
                                "surfaces so that texture reads at every distance.",
               "https://dezeen.com/a"),
            ev("Material Depth", "Stone and timber are left exposed; the structure spans "
                                 "the room and the geometry is legible from the door.",
               "https://domus.com/b"),
            ev("Threshold Work", "The route is arranged so the volume is revealed after "
                                 "the threshold, with daylight doing the work.",
               "https://frameweb.com/c")]
    commercial = [ev("Retail ROI", "Boost conversion and sales with loyalty campaigns "
                                   "that raise footfall and drive revenue per shopper.",
                     "https://dezeen.com/a"),
                  ev("Marketing Wins", "Personalisation and CRM campaigns lift customer "
                                       "purchase rates and brand recall for shoppers.",
                     "https://domus.com/b"),
                  ev("Sales Playbook", "Discounts and price campaigns drive turnover "
                                       "across every SKU in the store.",
                     "https://frameweb.com/c")]
    a = estimate_design_value(rich, TrendDomain.ARCHITECTURE)
    b = estimate_design_value(commercial, TrendDomain.BRAND_DESIGN)
    assert a.estimate is not None and b.estimate is not None
    assert a.estimate > b.estimate


def test_every_estimate_states_its_features_and_its_reason():
    est = estimate_design_value(
        [ev("A", "Light and stone and timber and texture across the whole plan."),
         ev("B", "The geometry spans the room and the material is left exposed.",
            "https://domus.com/b"),
         ev("C", "Daylight is used so the surface reads from the threshold.",
            "https://frameweb.com/c")],
        TrendDomain.ARCHITECTURE)
    assert set(est.features) == {"spatial_lexicon", "transferability",
                                 "domain_prior", "source_signal"}
    assert est.reason and "estimated from" in est.reason


def test_confidence_below_the_threshold_always_means_no_number():
    for domain in (TrendDomain.ART, TrendDomain.MOVIES, TrendDomain.TRAVEL):
        est = estimate_design_value([ev("t", "x")], domain)
        assert est.confidence < MIN_CONFIDENCE
        assert est.estimate is None


def test_an_uncertain_candidate_is_barred_and_says_why():
    p = WebSearchTrendProvider(RecordedSearchBackend(), today=TODAY)
    from app.providers.trend.web import _Cluster
    rows = [SearchResult(title="Something Happened", url="https://example.org/a", snippet="x")]
    c = p._to_candidate(_Cluster(rows, "something"), TrendDomain.CULTURE, ["q"], TODAY)
    assert c is not None                       # kept for the debug view
    assert c.design_value_estimate is None
    assert c.design_value_uncertain is True
    assert c.low_confidence is True
    assert "design value uncertain" in c.rejected_reason
