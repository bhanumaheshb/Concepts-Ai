"""Trend discovery routes.

`/discover` is callable on its own so a designer can inspect what was found — and why —
before spending an exploration.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.composition import get_container
from app.creative.program import build_program
from app.domain.brief import DesignBrief
from app.domain.trend import TrendDiscoveryRequest, TrendDomain, TrendMode

router = APIRouter(prefix="/api/trends", tags=["trends"])


class DiscoverRequest(BaseModel):
    brief: str = Field(min_length=4)
    location: str | None = None
    project_type: str | None = None
    mode: TrendMode = TrendMode.CURRENT_INSPIRATION
    domains: list[TrendDomain] = []
    max_candidates: int = 8
    max_selected: int = 3
    seed: int = 42
    today: date | None = None


def _program(req: DiscoverRequest):
    c = get_container()
    from app.domain.common import Typology
    typ = Typology.GENERIC_SPATIAL
    if req.project_type:
        try:
            typ = Typology(req.project_type)
        except ValueError:
            pass
    brief = DesignBrief(brief_id="bf_trend_preview", raw_text=req.brief,
                        typology=typ, location=req.location)
    return c.ontology, build_program(c.ontology, brief), brief


def _candidate_payload(c) -> dict:
    return {
        "candidate_id": c.candidate_id, "title": c.title, "domain": c.domain.value,
        "summary": c.summary, "score": round(c.score, 4),
        "freshness": c.freshness.value, "why_selected": c.why_selected,
        "signal": c.signal.model_dump(mode="json"),
        "corroboration": c.corroboration,
        "evidence": [e.model_dump(mode="json") for e in c.evidence],
        "principle_hints": [h.model_dump(mode="json") for h in c.principle_hints],
        "literal_label": c.literal_label,
        "is_mock": c.is_mock,
        # live-discovery provenance
        "entity": c.entity,
        "independent_sources": c.independent_sources,
        "low_confidence": c.low_confidence,
        "freshness_confidence": c.freshness_confidence,
        "freshness_evidence": c.freshness_evidence,
        "design_value_estimate": c.design_value_estimate,
        "design_value_confidence": c.design_value_confidence,
        "design_value_uncertain": c.design_value_uncertain,
        "design_value_reason": c.design_value_reason,
        "rejected_reason": c.rejected_reason,
        "notes": c.notes,
        "sources": sorted({e.publisher or e.source for e in c.evidence}),
    }


def _result_payload(r) -> dict:
    return {
        "result_id": r.result_id, "mode": r.mode.value, "provider": r.provider,
        "is_mock": r.is_mock, "notes": r.notes, "region": r.region,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "plan": [p.model_dump(mode="json") for p in r.plan],
        "queries": r.queries, "cached_queries": r.cached_queries,
        "candidates": [_candidate_payload(c) for c in r.candidates],
        "selected_ids": r.selected_ids,
        "domain_spread": r.domain_spread(),
        # health — the UI must be able to tell live from recorded from mock
        "unavailable": r.unavailable,
        "failed_domains": r.failed_domains,
        "search_calls": r.search_calls,
        "raw_results": r.raw_results,
        "rejected": r.rejected,
        "evidence_mode": _evidence_mode(r),
        "source_count": len({e.publisher or e.source
                             for c in r.candidates for e in c.evidence}),
    }


def _evidence_mode(r) -> str:
    """MOCK · RECORDED · LIVE. Never inferred from a single flag: 'not mock' does not
    mean live, and the UI must not be able to make that mistake."""
    if r.is_mock:
        return "MOCK"
    c = get_container()
    return "LIVE" if getattr(c.trends.provider, "is_live", False) else "RECORDED"


@router.get("/domains")
def domains() -> dict:
    c = get_container()
    return {
        "domains": [d.value for d in TrendDomain],
        "modes": [m.value for m in TrendMode],
        "fixture_domains": [d.value for d in c.trends.provider.domains_available()],
        "provider": {"name": c.trends.provider.name,
                     "live": getattr(c.trends.provider, "is_live", False),
                     "mock": getattr(c.trends.provider, "is_mock", True),
                     "configured": c.trends.provider.is_configured()},
    }


@router.post("/plan")
def plan(req: DiscoverRequest) -> dict:
    """Domain selection only — no provider call, so it is cheap enough to run on typing."""
    _, program, _ = _program(req)
    c = get_container()
    tr = TrendDiscoveryRequest(mode=req.mode, domains=req.domains, seed=req.seed)
    plan = c.trends.plan(program, req.brief, tr, req.today or date.today())
    return {"plan": [p.model_dump(mode="json") for p in plan],
            "typology": program.typology.value}


@router.post("/discover")
def discover(req: DiscoverRequest) -> dict:
    if req.mode is TrendMode.OFF:
        raise HTTPException(422, "mode OFF performs no discovery")
    c = get_container()
    _, program, _ = _program(req)
    tr = TrendDiscoveryRequest(
        mode=req.mode, domains=req.domains, max_candidates=req.max_candidates,
        max_selected=req.max_selected, region=req.location, seed=req.seed)
    result = c.trends.discover(program, req.brief, tr, req.today or date.today())
    c.store.put_trend(result)
    return _result_payload(result)
