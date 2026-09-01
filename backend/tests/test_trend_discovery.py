"""Domain selection, query generation, scoring, freshness and diverse selection."""
from datetime import date, timedelta

import pytest

from app.creative.program import build_program
from app.domain.brief import DesignBrief
from app.domain.trend import (
    PrincipleHint, SourceTier, TrendCandidate, TrendDomain as D, TrendEvidence,
    TrendFreshness, TrendMode, TrendSignal,
)
from app.trends.domains import select_domains
from app.trends.queries import build_queries
from app.trends.scoring import (
    DESIGN_VALUE_FLOOR, POPULARITY_CAP, classify_freshness, score_candidate,
    source_quality, tier_for,
)
from app.trends.selection import select_diverse


def _program(ont, text):
    return build_program(ont, DesignBrief(brief_id="bf_t", raw_text=text))


def _cand(cid, domain, *, design_value=0.8, momentum=0.5, sources=2,
          published=date(2026, 6, 1), tier=SourceTier.MAJOR_PUBLICATION, novelty=0.6):
    return TrendCandidate(
        candidate_id=cid, title=f"signal {cid}", domain=domain,
        evidence=[TrendEvidence(source=f"MOCK FIXTURE · src{i}", source_tier=tier,
                                published=published, is_mock=True)
                  for i in range(sources)],
        signal=TrendSignal(design_value=design_value, momentum=momentum,
                           relevance=0.75, novelty=novelty, source_quality=0.8),
        is_mock=True,
    )


# ── domain selection ─────────────────────────────────────────────

def test_domains_differ_by_brief(ont):
    a = {p.domain for p in select_domains(
        _program(ont, "Luxury Sangeeth for 500 guests"),
        "Luxury Sangeeth for 500 guests", TrendMode.CURRENT_INSPIRATION)}
    b = {p.domain for p in select_domains(
        _program(ont, "A futuristic restaurant interior"),
        "A futuristic restaurant interior", TrendMode.CURRENT_INSPIRATION)}
    assert a != b, "domain selection is not brief-aware"
    assert D.WEDDING_DESIGN in a
    assert D.HOSPITALITY in b or D.INTERIOR_DESIGN in b


def test_movies_are_not_privileged(ont):
    """Movies/TV are two of twenty-six categories, never a default."""
    for text in ("Luxury Sangeeth for 500 guests", "A luxury retail flagship store",
                 "A quiet memorial pavilion"):
        doms = {p.domain for p in select_domains(_program(ont, text), text,
                                                 TrendMode.CURRENT_INSPIRATION)}
        assert D.MOVIES not in doms and D.TV_SERIES not in doms


def test_custom_mode_uses_exactly_the_user_list(ont):
    custom = [D.ARCHITECTURE, D.FASHION, D.TECHNOLOGY]
    plan = select_domains(_program(ont, "A luxury retail flagship store"),
                          "A luxury retail flagship store", TrendMode.CUSTOM, custom)
    assert [p.domain for p in plan] == custom
    assert all(p.rationale == "chosen by the designer" for p in plan)


def test_design_trends_mode_lifts_the_design_cluster(ont):
    text = "Create a Sangeeth concept"
    base = {p.domain for p in select_domains(_program(ont, text), text,
                                             TrendMode.CURRENT_INSPIRATION)}
    design = {p.domain for p in select_domains(_program(ont, text), text,
                                               TrendMode.DESIGN_TRENDS)}
    assert design != base


def test_surprise_me_injects_far_domains(ont):
    text = "Create a crazy Sangeeth concept"
    plan = select_domains(_program(ont, text), text, TrendMode.SURPRISE_ME, seed=42)
    far = [p for p in plan if "distant" in p.rationale]
    assert len(far) == 2, "SURPRISE_ME must reach outside the obvious domains"


def test_domain_selection_is_deterministic(ont):
    text = "Create a crazy Sangeeth concept"
    a = select_domains(_program(ont, text), text, TrendMode.SURPRISE_ME, seed=7)
    b = select_domains(_program(ont, text), text, TrendMode.SURPRISE_ME, seed=7)
    assert [p.domain for p in a] == [p.domain for p in b]


# ── queries ──────────────────────────────────────────────────────

def test_queries_are_built_from_the_brief_not_a_template(ont, today):
    p1 = _program(ont, "Luxury Sangeeth for 500 guests")
    p2 = _program(ont, "A futuristic restaurant interior")
    q1 = build_queries(p1, "Luxury Sangeeth for 500 guests",
                       select_domains(p1, "Luxury Sangeeth", TrendMode.CURRENT_INSPIRATION),
                       TrendMode.CURRENT_INSPIRATION, None, today)
    q2 = build_queries(p2, "A futuristic restaurant interior",
                       select_domains(p2, "A futuristic restaurant interior",
                                      TrendMode.CURRENT_INSPIRATION),
                       TrendMode.CURRENT_INSPIRATION, None, today)
    assert {q for p in q1 for q in p.queries} != {q for p in q2 for q in p.queries}
    assert all(str(today.year) in " ".join(p.queries) for p in q1)


def test_location_only_appears_when_given(ont, today):
    p = _program(ont, "Luxury Sangeeth")
    plan = select_domains(p, "Luxury Sangeeth", TrendMode.CURRENT_INSPIRATION)
    without = build_queries(p, "Luxury Sangeeth", plan, TrendMode.CURRENT_INSPIRATION,
                            None, today)
    withloc = build_queries(p, "Luxury Sangeeth", plan, TrendMode.CURRENT_INSPIRATION,
                            "Hyderabad", today)
    assert not any("hyderabad" in q.lower() for p_ in without for q in p_.queries)
    assert any("hyderabad" in q.lower() for p_ in withloc for q in p_.queries)


# ── source quality ───────────────────────────────────────────────

def test_source_tiers_rank_as_specified():
    assert tier_for("dezeen architecture") is SourceTier.MAJOR_PUBLICATION
    assert tier_for("some.gov portal") is SourceTier.OFFICIAL
    assert tier_for("instagram post") is SourceTier.SOCIAL
    assert tier_for("unknown site") is SourceTier.AGGREGATOR


def test_corroboration_raises_source_quality():
    one = _cand("a", D.ART, sources=1)
    two = _cand("b", D.ART, sources=3)
    assert source_quality(two) > source_quality(one)


# ── scoring ──────────────────────────────────────────────────────

def test_popularity_does_not_beat_design_value(today):
    """§9 — the rule this module exists to enforce."""
    popular = _cand("pop", D.TV_SERIES, design_value=0.20, momentum=0.98, novelty=0.3)
    obscure = _cand("obs", D.ARCHITECTURE, design_value=0.95, momentum=0.25, novelty=0.8)
    sp = score_candidate(popular, TrendMode.TRENDING_NOW, today)
    so = score_candidate(obscure, TrendMode.TRENDING_NOW, today)
    assert sp <= POPULARITY_CAP, "the low-design-value cap did not fire"
    assert so > sp, "a popular signal with no design value outranked a useful one"


def test_a_single_viral_post_is_not_a_trend(today):
    solo = _cand("solo", D.SOCIAL_VISUAL_CULTURE, momentum=1.0, sources=1,
                 tier=SourceTier.SOCIAL)
    backed = _cand("backed", D.SOCIAL_VISUAL_CULTURE, momentum=1.0, sources=3,
                   tier=SourceTier.MAJOR_PUBLICATION)
    assert score_candidate(backed, TrendMode.TRENDING_NOW, today) > \
           score_candidate(solo, TrendMode.TRENDING_NOW, today)


def test_mode_reweights_but_the_cap_always_applies(today):
    weak = _cand("w", D.GAMES, design_value=0.1, momentum=1.0, novelty=1.0)
    for mode in (TrendMode.TRENDING_NOW, TrendMode.SURPRISE_ME, TrendMode.DESIGN_TRENDS,
                 TrendMode.CULTURAL_MOMENT, TrendMode.CURRENT_INSPIRATION):
        assert score_candidate(weak, mode, today) <= POPULARITY_CAP


def test_scores_stay_in_range(today):
    for dv in (0.0, 0.34, 0.35, 1.0):
        c = _cand("x", D.ART, design_value=dv)
        assert 0.0 <= score_candidate(c, TrendMode.CURRENT_INSPIRATION, today) <= 1.0


# ── freshness ────────────────────────────────────────────────────

def test_an_old_article_is_never_trending_now(today):
    old = _cand("old", D.ART, published=today - timedelta(days=700), momentum=0.95)
    assert classify_freshness(old, today) is TrendFreshness.DECLINING


def test_freshness_classes(today):
    emerging = _cand("e", D.ART, published=today - timedelta(days=30),
                     sources=2, momentum=0.8)
    assert classify_freshness(emerging, today) is TrendFreshness.EMERGING
    current = _cand("c", D.ART, published=today - timedelta(days=200),
                    sources=2, momentum=0.3)
    assert classify_freshness(current, today) is TrendFreshness.CURRENT


def test_no_dates_does_not_crash(today):
    c = TrendCandidate(candidate_id="nd", title="t", domain=D.ART, is_mock=True,
                       evidence=[TrendEvidence(source="MOCK FIXTURE · x", is_mock=True)])
    assert classify_freshness(c, today) in set(TrendFreshness)


# ── diverse selection ────────────────────────────────────────────

def test_selection_spreads_across_domains(ont, today):
    cands = []
    for i in range(4):
        c = _cand(f"arch{i}", D.ARCHITECTURE, design_value=0.95)
        cands.append(c.model_copy(update={"score": 0.9 - i * 0.01}))
    cands.append(_cand("fash", D.FASHION).model_copy(update={"score": 0.75}))
    cands.append(_cand("art", D.ART).model_copy(update={"score": 0.72}))
    plan = select_domains(_program(ont, "Luxury Sangeeth"), "Luxury Sangeeth",
                          TrendMode.CURRENT_INSPIRATION)
    chosen = select_diverse(cands, 3, plan)
    assert len({c.domain for c in chosen}) >= 2, "selection collapsed onto one domain"


def test_selection_is_deterministic(ont):
    cands = [_cand(f"c{i}", D.ART).model_copy(update={"score": 0.8 - i * 0.05})
             for i in range(5)]
    plan = select_domains(_program(ont, "x"), "x", TrendMode.CURRENT_INSPIRATION)
    assert [c.candidate_id for c in select_diverse(cands, 3, plan)] == \
           [c.candidate_id for c in select_diverse(cands, 3, plan)]
