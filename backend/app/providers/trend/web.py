"""WebSearchTrendProvider — real search results in, evidence-backed candidates out.

What this provider is allowed to claim is bounded by what it actually retrieved:
  * no evidence            → no candidate;
  * no dated evidence      → low_confidence, and freshness is not asserted as CURRENT;
  * thin evidence          → design_value is None and the candidate is barred, not guessed;
  * one publisher          → corroboration 1, momentum stays at the floor.

Retrieved text is data. It is used to detect dimensions and to extract metadata; it is
never placed in an instruction position and never copied into the creative engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.core.ids import deterministic_id
from app.domain.reference import ReferenceType, detect_proper_nouns
from app.domain.trend import (
    TIER_SCORE, SourceTier, TrendCandidate, TrendDomain, TrendEvidence, TrendSignal,
)
from app.providers.trend.design_value import estimate_design_value
from app.providers.trend.extraction import (
    STOPWORDS, collapse_syndication, independent_sources, normalise_title,
    registrable_host, resolve_entity, similarity, to_evidence,
)
from app.providers.trend.hints import hints_from_evidence
from app.providers.trend.search_backend import SearchBackend, SearchError, SearchResult

CLUSTER_THRESHOLD = 0.42          # title-token overlap that makes two results one signal
MIN_EVIDENCE = 1

# Display only. TRD-06 still analyses every trend as ReferenceType.OTHER — a discovered
# signal is a cross-domain observation, not a typed work.
DOMAIN_TYPE: dict[TrendDomain, ReferenceType] = {
    TrendDomain.ARCHITECTURE: ReferenceType.ARCHITECTURE,
    TrendDomain.INTERIOR_DESIGN: ReferenceType.ARCHITECTURE,
    TrendDomain.FASHION: ReferenceType.FASHION,
    TrendDomain.ART: ReferenceType.ART,
    TrendDomain.MOVIES: ReferenceType.MOVIE,
    TrendDomain.TV_SERIES: ReferenceType.TV_SERIES,
    TrendDomain.GAMES: ReferenceType.GAME,
    TrendDomain.NATURE: ReferenceType.NATURE,
    TrendDomain.TECHNOLOGY: ReferenceType.TECHNOLOGY,
    TrendDomain.PHOTOGRAPHY: ReferenceType.PHOTOGRAPHY,
    TrendDomain.CULTURE: ReferenceType.CULTURAL_REFERENCE,
}


@dataclass
class _Cluster:
    results: list[SearchResult] = field(default_factory=list)
    key: str = ""


def _cluster(results: list[SearchResult]) -> list[_Cluster]:
    """Group results that are about the same signal. Independence is counted AFTER
    this, so a cluster of five copies of one story is not five sources."""
    clusters: list[_Cluster] = []
    for r in results:
        norm = normalise_title(r.title)
        placed = False
        for c in clusters:
            if similarity(norm, c.key) >= CLUSTER_THRESHOLD or _token_overlap(norm, c.key) >= 0.5:
                c.results.append(r)
                placed = True
                break
        if not placed:
            clusters.append(_Cluster([r], norm))
    return clusters


def _token_overlap(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / max(1, min(len(ta), len(tb))) if ta and tb else 0.0


def _recency(evidence: list[TrendEvidence], today: date) -> tuple[float, float, list[str]]:
    """Returns (recency, freshness_confidence, dated urls). Undated evidence lowers
    confidence — it never becomes an assumed recent date."""
    dated = [e for e in evidence if e.published]
    if not dated:
        return 0.0, 0.0, []
    newest = max(e.published for e in dated)          # type: ignore[type-var]
    age_days = max(0, (today - newest).days)
    recency = max(0.0, 1.0 - age_days / 540.0)
    confidence = round(len(dated) / len(evidence), 3)
    return round(recency, 3), confidence, [e.url for e in dated if e.url]


def _relevance(evidence: list[TrendEvidence], queries: list[str]) -> float:
    qt = {w for q in queries for w in normalise_title(q).split()} - STOPWORDS
    if not qt:
        return 0.5
    text = {w for e in evidence for w in normalise_title(f"{e.title} {e.excerpt}").split()}
    return round(min(1.0, len(qt & text) / len(qt)), 3)


def _is_title_case(text: str) -> bool:
    words = [w for w in text.split() if len(w) > 3]
    if len(words) < 3:
        return False
    return sum(1 for w in words if w[:1].isupper()) / len(words) >= 0.6


def _real_proper_nouns(evidence: list[TrendEvidence]) -> list[str]:
    """Extract brand and project names WITHOUT confiscating ordinary design vocabulary.

    `detect_proper_nouns` reads a mid-sentence capital as a name — correct for prose,
    useless for a headline, where Title Case capitalises every word and "Design",
    "Materiality" and "Shaping" all look like names. So a Title Case title contributes
    nothing; names are taken from the sentence-case excerpt, where a capital still
    carries information.
    """
    out: list[str] = []
    corpus = " ".join(f"{e.title} {e.excerpt}" for e in evidence)
    # a genuine name is never written lowercase in the same corpus
    lowercased = {w.strip(".,;:!?()\"'").lower() for w in corpus.split() if w[:1].islower()}
    for e in evidence:
        if e.title and not _is_title_case(e.title):
            out.extend(detect_proper_nouns(e.title))
        if e.excerpt and not _is_title_case(e.excerpt):
            out.extend(detect_proper_nouns(e.excerpt))
    return sorted({t for t in dict.fromkeys(out)
                   if len(t) >= 4 and t.lower() not in STOPWORDS
                   and t.lower() not in lowercased})


class WebSearchTrendProvider:
    """Wraps a SearchBackend. `is_live` mirrors the backend: a recorded transport is
    honest about not being live even though its evidence is real."""

    def __init__(self, backend: SearchBackend, *, max_queries: int = 12,
                 max_sources: int = 6, today: date | None = None) -> None:
        self.backend = backend
        self.max_queries = max_queries
        self.max_sources = max_sources
        self._today = today
        self.name = f"web:{backend.name}"
        # is_live == the transport really goes to the web right now.
        # is_mock == the evidence is invented. A recorded backend is neither: its
        # evidence is real, its transport is not live, and both facts are reported.
        self.is_live = bool(getattr(backend, "is_live", False))
        self.is_mock = False
        self.search_calls = 0
        self.last_error: str | None = None
        self.rejected: list[dict] = []

    # ---- protocol ----------------------------------------------------------
    def is_configured(self) -> bool:
        return self.backend.is_configured()

    def domains_available(self) -> list[TrendDomain]:
        """Search is not domain-limited: any domain the planner asks for can be queried."""
        return list(TrendDomain)

    def discover(self, *, queries: list[str], domain: TrendDomain, limit: int = 3,
                 seed: int = 0) -> list[TrendCandidate]:
        today = self._today or date.today()
        results: list[SearchResult] = []
        used: list[str] = []
        failures = 0
        for q in queries[: self.max_queries]:
            try:
                found = self.backend.search(q, limit=8)
            except SearchError as exc:                 # one failed query is not fatal
                self.last_error = str(exc)
                failures += 1
                continue
            self.search_calls += 1
            used.append(q)
            results.extend(found)
        if not used and failures:
            # every query for this domain failed: that is a search outage, not an empty
            # result set, and the caller must be able to tell the difference.
            raise SearchError(f"all {failures} queries failed: {self.last_error}")
        if not results:
            return []

        candidates: list[TrendCandidate] = []
        for cluster in _cluster(results):
            candidate = self._to_candidate(cluster, domain, used, today)
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(key=lambda c: (-c.corroboration,
                                       -(c.signal.design_value or 0.0), c.candidate_id))
        return candidates[:limit]

    # ---- one cluster → one candidate --------------------------------------
    def _to_candidate(self, cluster: _Cluster, domain: TrendDomain,
                      queries: list[str], today: date) -> TrendCandidate | None:
        evidence: list[TrendEvidence] = []
        injection_seen = False
        for r in cluster.results:
            ev, flagged = to_evidence(r)
            injection_seen = injection_seen or flagged
            evidence.append(ev)
        evidence, notes = collapse_syndication(evidence)
        evidence = sorted(evidence, key=lambda e: -TIER_SCORE[e.source_tier])[: self.max_sources]
        if len(evidence) < MIN_EVIDENCE:
            return None

        independent = independent_sources(evidence)
        # policy: a demoted (content-farm) source may corroborate but never stand alone
        if independent == 1 and evidence[0].source_tier == SourceTier.SOCIAL:
            self.rejected.append({"title": evidence[0].title,
                                  "reason": "single demoted source"})
            return None

        entity = resolve_entity([e.title for e in evidence], domain.value.lower().replace("_", " "))
        recency, fresh_conf, fresh_urls = _recency(evidence, today)
        dv = estimate_design_value(evidence, domain)

        best_tier = max(TIER_SCORE[e.source_tier] for e in evidence)
        # momentum counts INDEPENDENT and RECENT evidence only, and stays at the floor
        # when the evidence cannot support it
        recent_independent = len({registrable_host(e.url or "") for e in evidence
                                  if e.published and (today - e.published).days <= 270})
        momentum = 0.0 if recent_independent < 2 else min(1.0, 0.35 + 0.2 * recent_independent)

        hints = hints_from_evidence(evidence)
        surface = _real_proper_nouns(evidence)

        signal = TrendSignal(
            recency=recency,
            momentum=round(momentum, 3),
            relevance=_relevance(evidence, queries),
            design_value=dv.estimate if dv.estimate is not None else 0.0,
            source_quality=round(min(1.0, best_tier + min(0.10, 0.05 * (independent - 1))), 3),
            novelty=round(max(0.15, 1.0 - min(1.0, independent / 6.0)), 3),
            cross_domain_potential=round(min(1.0, 0.45 + 0.12 * len(hints)), 3),
        )

        cid = deterministic_id("tc", domain.value, entity,
                               evidence[0].canonical_url or evidence[0].title)[:20]
        low_confidence = fresh_conf == 0.0 or dv.uncertain or len(hints) < 2
        reason = "; ".join(filter(None, [
            "no dated evidence" if fresh_conf == 0.0 else "",
            "design value uncertain" if dv.uncertain else "",
            "fewer than 2 transferable readings" if len(hints) < 2 else "",
        ]))

        return TrendCandidate(
            candidate_id=cid,
            title=entity.title(),                      # resolved identity, not a headline
            domain=domain,
            summary=f"A {domain.value.lower().replace('_', ' ')} signal about {entity}, "
                    f"reported by {independent} independent source"
                    f"{'s' if independent != 1 else ''}.",
            evidence=evidence,
            signal=signal,
            principle_hints=hints,
            surface_terms=surface[:8],
            literal_label=f"a literal rendering of {entity}",
            naive_rendering=f"A direct visual copy of what '{entity}' looks like in "
                            f"{domain.value.lower().replace('_', ' ')}, reproduced as set "
                            f"dressing rather than interpreted as a spatial idea.",
            suggested_reference_type=DOMAIN_TYPE.get(domain, ReferenceType.OTHER),
            is_mock=False,
            entity=entity,
            independent_sources=independent,
            low_confidence=low_confidence,
            freshness_confidence=fresh_conf,
            freshness_evidence=fresh_urls,
            design_value_estimate=dv.estimate,
            design_value_confidence=dv.confidence,
            design_value_uncertain=dv.uncertain,
            design_value_reason=dv.reason,
            rejected_reason=reason,
            queries=list(queries),
            notes=" · ".join(notes + (["injection markers stripped from retrieved text"]
                                      if injection_seen else [])),
        )
