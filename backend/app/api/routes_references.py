"""Reference Intelligence routes.

`/injection` is callable on its own so the UI can show the DNA and the extracted
principles BEFORE the designer commits to a full exploration (R-REF-16).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.composition import get_container
from app.domain.reference import (
    ReferencePreset, ReferenceRequest, ReferenceSelector, ReferenceType,
)
from app.references.compatibility import classify
from app.references.injection import build_injection

router = APIRouter(prefix="/api/references", tags=["references"])


class AnalyseRequest(BaseModel):
    query: str = Field(min_length=1)
    kind: ReferenceType | None = None
    seed: int = 0


class CompatibilityRequest(BaseModel):
    reference_ids: list[str] = Field(min_length=2, max_length=4)


class InjectionRequest(BaseModel):
    references: list[str] = Field(min_length=1, max_length=4)   # ids or free-text queries
    influence: float = 0.55
    preset: ReferencePreset = ReferencePreset.INSPIRED_BY
    synthesis: bool = True
    seed: int = 42


def _dna_payload(dna) -> dict:
    return {
        "dna_id": dna.dna_id,
        "identity": dna.identity.model_dump(mode="json"),
        "traits": [t.model_dump(mode="json") for t in dna.traits],
        "literal_reading": dna.literal_reading.model_dump(mode="json"),
        "surface_lexicon": [t.model_dump(mode="json") for t in dna.surface_lexicon.tokens],
        "coverage": [c.model_dump(mode="json") for c in dna.coverage],
        "analyser": dna.analyser,
    }


def _principle_payload(p) -> dict:
    return {
        "id": p.id, "source_domain": p.source_domain, "domain_class": p.domain_class,
        "statements": list(p.statements), "mappable_to": list(p.mappable_to),
        "biases": {k: list(v) for k, v in p.biases.items()},
        "forbidden_surface_tokens": list(p.forbidden_surface_tokens),
        "salience": p.salience, "requires_reconciliation": p.requires_reconciliation,
        "provenance": {
            "source": p.provenance.source,
            "reference_ids": list(p.provenance.reference_ids),
            "derived_from_traits": list(p.provenance.derived_from_traits),
            "abstraction": p.provenance.abstraction,
            "dimension": p.provenance.dimension,
        },
    }


@router.get("/search")
def search(q: str, kind: ReferenceType | None = None) -> dict:
    svc = get_container().references
    hits = svc.search(q, kind)
    return {
        "results": [
            {"reference_id": i.reference_id, "display_name": i.display_name,
             "kind": i.kind.value, "resolved_by": i.resolved_by,
             "confidence": i.confidence, "blurb": i.blurb}
            for i in hits
        ],
        "analyse_available": True,      # unresolved queries still produce a usable DNA
    }


@router.post("/analyse")
def analyse(req: AnalyseRequest) -> dict:
    svc = get_container().references
    dna = svc.analyzer.analyse(query=req.query, kind=req.kind, seed=req.seed)
    return _dna_payload(dna)


@router.get("/{reference_id}")
def get_reference(reference_id: str) -> dict:
    svc = get_container().references
    if reference_id not in svc.analyzer.known_ids():
        raise HTTPException(404, f"reference {reference_id} not found")
    return _dna_payload(svc.dna(reference_id))


@router.get("/{reference_id}/principles")
def get_principles(reference_id: str, influence: float = 0.55) -> dict:
    c = get_container()
    svc = c.references
    if reference_id not in svc.analyzer.known_ids():
        raise HTTPException(404, f"reference {reference_id} not found")
    dna = svc.dna(reference_id)
    request = ReferenceRequest(references=[ReferenceSelector(query=reference_id)],
                               influence=influence)
    inj = build_injection(c.ontology, [dna], request, None, seed=0)
    return {
        "reference_id": reference_id,
        "influence": inj.influence.model_dump(mode="json"),
        "principles": [_principle_payload(p) for p in inj.principles],
        "removed_tokens": [t.model_dump(mode="json") for t in inj.surface_lexicon.tokens],
        "abstraction_log": [a.model_dump(mode="json") for a in inj.abstraction_log],
    }


@router.post("/compatibility")
def compatibility(req: CompatibilityRequest) -> dict:
    c = get_container()
    svc = c.references
    dnas = []
    for rid in req.reference_ids:
        if rid not in svc.analyzer.known_ids():
            raise HTTPException(404, f"reference {rid} not found")
        dnas.append(svc.dna(rid))
    result = classify(c.ontology, dnas)
    return result.model_dump(mode="json")


@router.post("/injection")
def injection(req: InjectionRequest) -> dict:
    """R-REF-16 — the pre-Generate preview. No exploration is spent."""
    c = get_container()
    request = ReferenceRequest(
        references=[ReferenceSelector(query=r) for r in req.references],
        influence=req.influence, preset=req.preset, synthesis=req.synthesis,
    )
    out = c.references.build(request, None, seed=req.seed)
    if not out.ok:
        return {
            "ok": False,
            "ambiguous": [[i.model_dump(mode="json") for i in cands] for cands in out.ambiguous],
            "message": "Ambiguous reference — choose one of the candidates.",
        }
    inj = out.injection
    return {
        "ok": True,
        "injection_id": inj.injection_id,
        "influence": inj.influence.model_dump(mode="json"),
        "compatibility": inj.compatibility.model_dump(mode="json") if inj.compatibility else None,
        "reference_dnas": [_dna_payload(d) for d in inj.reference_dnas],
        "principles": [_principle_payload(p) for p in inj.principles],
        "removed_tokens": [t.model_dump(mode="json") for t in inj.surface_lexicon.tokens],
        "abstraction_log": [a.model_dump(mode="json") for a in inj.abstraction_log],
        "synthesis_log": [d.model_dump(mode="json") for d in inj.synthesis_log],
        "cliche_clusters": [cl.model_dump(mode="json") for cl in inj.cliche_clusters],
        "prior_bias": [b.model_dump(mode="json") for b in inj.prior_bias],
        "niche_assignment": inj.niche_assignment,
    }
