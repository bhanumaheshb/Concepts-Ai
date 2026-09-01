"""MockTrendProvider — deterministic fixtures, clearly marked as mock.

Mock trend data must never be mistakable for live data: every candidate carries
is_mock=True, and every evidence source is prefixed MOCK FIXTURE.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.domain.reference import ReferenceDimension, ReferenceType
from app.domain.trend import (
    PrincipleHint, SourceTier, TrendCandidate, TrendDomain, TrendEvidence, TrendSignal,
)

DATA_ROOT = Path(__file__).resolve().parents[2] / "trends" / "data"


@lru_cache(maxsize=4)
def _load(version: str) -> dict[TrendDomain, list[TrendCandidate]]:
    out: dict[TrendDomain, list[TrendCandidate]] = {}
    root = DATA_ROOT / version
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        domain = TrendDomain(raw["domain"])
        items: list[TrendCandidate] = []
        for c in raw["candidates"]:
            items.append(TrendCandidate(
                candidate_id=c["id"], title=c["title"], domain=domain,
                summary=" ".join(c.get("summary", "").split()),
                evidence=[TrendEvidence(
                    source=e["source"], source_tier=SourceTier(e.get("tier", "AGGREGATOR")),
                    published=e.get("published"), excerpt=e.get("excerpt", ""), is_mock=True)
                    for e in c["evidence"]],
                signal=TrendSignal(**c["signal"]),
                principle_hints=[PrincipleHint(
                    dimension=ReferenceDimension(h["dimension"]), statement=h["statement"],
                    abstraction=float(h.get("abstraction", 0.85)),
                    salience=float(h.get("salience", 0.7)),
                    suggests=list(h.get("suggests", [])))
                    for h in c.get("hints", [])],
                surface_terms=list(c.get("surface_terms", [])),
                literal_label=c.get("literal_label", ""),
                literal_facets=list(c.get("literal_facets", [])),
                naive_rendering=" ".join(c.get("naive_rendering", "").split()),
                suggested_reference_type=ReferenceType(c.get("reference_type", "OTHER")),
                is_mock=True,
            ))
        out[domain] = items
    return out


class MockTrendProvider:
    name = "mock"
    is_live = False
    is_mock = True

    def __init__(self, version: str = "v1") -> None:
        self._by_domain = _load(version)

    def is_configured(self) -> bool:
        return True

    def domains_available(self) -> list[TrendDomain]:
        return sorted(self._by_domain, key=lambda d: d.value)

    def discover(self, *, queries, domain: TrendDomain, limit: int,
                 seed: int = 0) -> list[TrendCandidate]:
        """Queries are recorded by the caller for the trace; the fixture provider
        answers by domain, which is what a live provider would resolve them to."""
        return list(self._by_domain.get(domain, []))[:limit]
