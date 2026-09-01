"""Trend Discovery orchestration: TRD-00 → TRD-06.

Produces a TrendDiscoveryResult, and converts a selection into the EXISTING
CreativePrincipleInjection. No concept generation happens here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.core.hashing import sha256_of
from app.core.ids import deterministic_id
from app.domain.brief import DesignProgram
from app.domain.reference import ReferenceDNA, ReferenceRequest, ReferenceSelector
from app.domain.trend import (
    TrendCandidate, TrendDiscoveryRequest, TrendDiscoveryResult, TrendDomain,
    TrendFreshness, TrendMode,
)
from app.ontology.graph import Ontology
from app.references.injection import build_injection
from app.trends.domains import select_domains
from app.trends.queries import build_queries
from app.trends.reference import candidate_to_dna
from app.trends.scoring import classify_freshness, explain, score_candidate
from app.domain.providers.protocols import SearchError
from app.trends.selection import select_diverse

CACHE_TTL_SECONDS = 6 * 3600
CANDIDATES_PER_DOMAIN = 3


@dataclass
class _CacheEntry:
    value: list[TrendCandidate]
    at: float


@dataclass
class TrendCache:
    """Keyed by normalised query + region + date bucket + mode (§21). One exploration
    never issues the same query twice."""
    ttl: float = CACHE_TTL_SECONDS
    _store: dict[str, _CacheEntry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @staticmethod
    def key(query: str, region: str | None, mode: TrendMode, today: date) -> str:
        bucket = today.strftime("%Y-%m-%d")
        return sha256_of({"q": " ".join(query.lower().split()),
                          "r": (region or "").lower(), "m": mode.value, "d": bucket})[:24]

    def get(self, key: str) -> list[TrendCandidate] | None:
        entry = self._store.get(key)
        if entry and (time.time() - entry.at) < self.ttl:
            self.hits += 1
            return entry.value
        self.misses += 1
        return None

    def put(self, key: str, value: list[TrendCandidate]) -> None:
        self._store[key] = _CacheEntry(value, time.time())


class TrendService:
    def __init__(self, ont: Ontology, provider, cache: TrendCache | None = None) -> None:
        self.ont = ont
        self.provider = provider
        self.cache = cache or TrendCache()

    # ---------- TRD-00 only: cheap, no provider call ----------
    def plan(self, program: DesignProgram, brief_text: str, request: TrendDiscoveryRequest,
             today: date | None = None):
        today = today or date.today()
        plan = select_domains(program, brief_text, request.mode,
                              request.domains or None, request.seed)
        return build_queries(program, brief_text, plan, request.mode, request.region, today)

    # ---------- TRD-01 → TRD-05 ----------
    def discover(self, program: DesignProgram, brief_text: str,
                 request: TrendDiscoveryRequest, today: date | None = None
                 ) -> TrendDiscoveryResult:
        today = today or date.today()
        plan = self.plan(program, brief_text, request, today)
        rationale = {p.domain: p.rationale for p in plan}

        all_queries: list[str] = []
        cached_queries: list[str] = []
        candidates: list[TrendCandidate] = []
        seen: set[str] = set()
        seen_content: set[tuple[str, str]] = set()
        failed_domains: list[str] = []
        is_live = bool(getattr(self.provider, "is_live", False))
        is_mock = bool(getattr(self.provider, "is_mock", not is_live))
        calls_before = int(getattr(self.provider, "search_calls", 0))

        for p in plan:
            key = self.cache.key(" | ".join(p.queries), request.region, request.mode, today)
            hit = self.cache.get(key)
            if hit is not None:
                cached_queries.extend(p.queries)
                found = hit
            else:
                try:
                    found = self.provider.discover(
                        queries=p.queries, domain=p.domain,
                        limit=CANDIDATES_PER_DOMAIN, seed=request.seed)
                except SearchError as exc:
                    # failure is per domain: one domain's outage must not cost the others,
                    # and it must never fail an exploration.
                    failed_domains.append(f"{p.domain.value}: {exc}")
                    all_queries.extend(p.queries)
                    continue
                self.cache.put(key, found)
            all_queries.extend(p.queries)

            for c in found:
                # Dedup by identity AND by content: the same signal reached from two
                # domain queries carries two ids but one set of evidence, and must not
                # occupy two selection slots.
                content_key = (c.entity.lower() or c.title.lower(),
                               (c.evidence[0].canonical_url or c.evidence[0].source)
                               if c.evidence else c.candidate_id)
                if c.candidate_id in seen or content_key in seen_content:
                    continue
                seen.add(c.candidate_id)
                seen_content.add(content_key)
                scored = c.model_copy(update={
                    "freshness": classify_freshness(c, today),
                    "score": score_candidate(c, request.mode, today),
                })
                candidates.append(scored.model_copy(update={
                    "why_selected": explain(scored, request.mode, today,
                                            rationale.get(c.domain, "relevant domain")),
                }))

        candidates.sort(key=lambda c: (-c.score, c.candidate_id))
        candidates = candidates[: request.max_candidates]

        # What bars a signal depends on what the mode CLAIMS.
        #
        #  * design value that could not be estimated from the evidence always bars it:
        #    that number feeds the ranking, and a guess would corrupt the ranking.
        #  * undated evidence bars it only in the modes whose claim IS recency. In
        #    DESIGN_TRENDS or SURPRISE_ME the claim is about transferable design content,
        #    and a well-corroborated undated source is legitimate inspiration — it is
        #    just never labelled fresh (its freshness reads UNDATED).
        recency_claiming = request.mode in (TrendMode.TRENDING_NOW,
                                            TrendMode.CULTURAL_MOMENT)

        def barred(c) -> str:
            if is_mock:
                return ""
            if c.design_value_uncertain:
                return "design value could not be estimated from the evidence"
            if recency_claiming and c.freshness is TrendFreshness.UNDATED:
                return f"{request.mode.value} claims recency, and no evidence is dated"
            return ""

        eligible = [c for c in candidates if not barred(c)]
        rejected = [f"{c.candidate_id}: {barred(c)}" for c in candidates if barred(c)]
        chosen = select_diverse(eligible, request.max_selected, plan)
        # UNAVAILABLE means the search layer is down, not that the search found nothing.
        # A domain that succeeded and returned no candidates is a result, not an outage.
        unavailable = bool(failed_domains) and len(failed_domains) == len(plan)

        return TrendDiscoveryResult(
            result_id=deterministic_id("td", program.program_id, request.mode.value,
                                       str(request.seed)),
            mode=request.mode, plan=plan, queries=all_queries, candidates=candidates,
            selected_ids=[c.candidate_id for c in chosen],
            provider=self.provider.name, is_mock=is_mock,
            cached_queries=cached_queries,
            generated_at=datetime.now(timezone.utc), region=request.region,
            notes=self._notes(is_live, is_mock, unavailable),
            unavailable=unavailable,
            failed_domains=failed_domains,
            search_calls=int(getattr(self.provider, "search_calls", 0)) - calls_before,
            raw_results=len(candidates),
            rejected=rejected,
        )

    @staticmethod
    def _notes(is_live: bool, is_mock: bool, unavailable: bool) -> str:
        """Three states, never conflated: invented, real-but-replayed, and live."""
        if unavailable:
            return "TREND_DISCOVERY_UNAVAILABLE — every domain search failed"
        if is_mock:
            return "MOCK TREND DATA — deterministic fixtures, not live discovery"
        if not is_live:
            return ("RECORDED EVIDENCE — real sources and real URLs, replayed over a "
                    "recorded transport. Not a live search.")
        return ""

    # ---------- TRD-06 → the EXISTING pipeline ----------
    def dnas_for(self, result: TrendDiscoveryResult,
                 candidate_ids: list[str] | None = None) -> list[ReferenceDNA]:
        by_id = {c.candidate_id: c for c in result.candidates}
        ids = candidate_ids or result.selected_ids
        return [candidate_to_dna(self.ont, by_id[i]) for i in ids if i in by_id]

    def injection_for(self, result: TrendDiscoveryResult, influence: float = 0.55,
                      candidate_ids: list[str] | None = None, space=None, seed: int = 42):
        """Hands off to the existing Reference Intelligence. Nothing new is generated."""
        dnas = self.dnas_for(result, candidate_ids)
        if not dnas:
            return None
        request = ReferenceRequest(
            references=[ReferenceSelector(query=d.identity.reference_id) for d in dnas],
            influence=influence, synthesis=True,
        )
        return build_injection(self.ont, dnas, request, space, seed)
