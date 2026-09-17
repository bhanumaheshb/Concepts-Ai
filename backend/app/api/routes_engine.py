"""Creative engine routes. Never touches an image provider."""
from __future__ import annotations

import threading

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.api.serializers import (
    concept_dna_rows,
    comparison_rows, concept_detail, debug_payload, exploration_payload,
)
from app.composition import get_container
from app.core import logging as elog
from app.persistence.sessions import SessionArchive
from app.core.ids import new_id
from app.core.seeded import SeededRandom
from app.creative.phenotype import synthesise_phenotype
from app.critics.runner import evaluate
from app.diversity.metric import genotype_distance
from app.domain.brief import DesignBrief
from app.domain.common import (
    EventType, NicheRole, Tradition, Typology, VenueType, ViewRole,
)
from app.domain.concept import ConceptDNA, Lineage
from app.mutation.operators import apply_operator, op_hybridise
from app.prompt.compiler import compile_prompt

router = APIRouter(prefix="/api", tags=["engine"])

_sessions = SessionArchive()
_lock = threading.Lock()


class ReferenceBlock(BaseModel):
    references: list[str] = Field(default_factory=list, max_length=4)
    influence: float = 0.55
    preset: str = "INSPIRED_BY"
    synthesis: bool = True


class TrendBlock(BaseModel):
    """Optional. Absent or mode=OFF => no discovery, no external call, no change."""
    mode: str = "OFF"
    domains: list[str] = []
    influence: float = 0.55
    max_selected: int = 3
    result_id: str | None = None          # reuse a discovery the UI already ran
    candidate_ids: list[str] = []         # designer's own selection from that result


class BriefRequest(BaseModel):
    project_type: str | None = None
    brief: str = Field(min_length=4)
    # What is happening, in whose tradition, in what kind of venue. All optional:
    # omitting them reproduces the pre-existing behaviour exactly.
    # Free text. A known value resolves against the knowledge base; anything else is
    # kept as the event's own name and programmed from its activities.
    event_type: str | None = None
    tradition: str | None = None        # HINDU | MUSLIM | CHRISTIAN | SIKH | SECULAR
    venue_type: str | None = None       # CONVENTION_SPACE (default) | LAWN | ...
    location: str | None = None
    dimensions: str | None = None
    budget: str | None = None
    constraints: str | None = None
    k: int = Field(default=10, ge=3, le=12)
    seed: int | None = None
    reference: ReferenceBlock | None = None      # omitted or null => current behaviour
    trend: TrendBlock | None = None              # omitted or OFF => no discovery at all


class MutateRequest(BaseModel):
    intent: str = "unexpected"     # unexpected | practical | similar | opposite
    operator: str | None = None
    pin: list[str] = []


class CombineRequest(BaseModel):
    other_id: str


class RateRequest(BaseModel):
    kind: str                       # selected | rejected | boring | wrong_culture | not_buildable
    reason_code: str = ""
    note: str = ""


def _record_or_404(exploration_id: str):
    rec = get_container().store.get(exploration_id)
    if rec is None:
        raise HTTPException(404, f"exploration {exploration_id} not found")
    return rec


def _find_concept(concept_id: str):
    store = get_container().store
    for eid in store.list_ids():
        rec = store.get(eid)
        c = rec.concept(concept_id)
        if c is not None:
            return rec, c
    raise HTTPException(404, f"concept {concept_id} not found")


@router.get("/health")
def health() -> dict:
    c = get_container()
    return {"status": "ok", "ontology_version": c.ontology.version,
            "ontology": c.ontology.stats()}


@router.get("/config")
def config() -> dict:
    c = get_container()
    return {
        "providers": c.provider_status(),
        "ontology": {"version": c.ontology.version, **c.ontology.stats()},
        "defaults": {"k": c.settings.default_k, "seed": c.settings.engine_seed},
        "image_generation_required": False,
        "typologies": [t.value for t in Typology],
        "event_types": [e.value for e in EventType],
        "traditions": [t.value for t in Tradition],
        "venue_types": [v.value for v in VenueType],
    }


class InterpretRequest(BaseModel):
    brief: str = Field(min_length=4)
    event_type: str | None = None
    tradition: str | None = None
    project_type: str | None = None
    use_model: bool = False      # the reasoning model is slow on a local server; opt in


@router.post("/semantics/interpret")
def interpret(req: InterpretRequest) -> dict:
    """Design Intelligence on its own: what the engine understands a brief to be,
    without running the creative search. Deterministic unless `use_model` is set."""
    from app.creative.program import estimate_capacity
    from app.semantics.intelligence import DesignIntelligence
    c = get_container()
    try:
        typology = Typology(req.project_type) if req.project_type else Typology.GENERIC_SPATIAL
    except ValueError:
        typology = Typology.GENERIC_SPATIAL
    try:
        tradition = Tradition(req.tradition) if req.tradition else Tradition.UNSPECIFIED
    except ValueError:
        tradition = Tradition.UNSPECIFIED
    brief = DesignBrief(brief_id=new_id("bf"), raw_text=req.brief, typology=typology,
                        event_type_text=(req.event_type or "").strip() or None,
                        tradition=tradition)
    intelligence = c.pipeline.intelligence if req.use_model else DesignIntelligence(
        c.pipeline.intelligence.k)
    sb = intelligence.understand(brief, capacity=estimate_capacity(brief))
    return sb.model_dump(mode="json")


@router.get("/semantics/knowledge")
def knowledge_catalogue() -> dict:
    """What the knowledge base knows. Unknown events are still accepted."""
    from app.semantics.knowledge import load_knowledge
    k = load_knowledge()
    return {
        "version": k.version,
        "families": {key: f.label for key, f in k.families.items()},
        "event_types": [{"key": e.key, "label": e.label, "family": e.family,
                         "traditions": sorted(e.traditions)} for e in k.event_types.values()],
        # "Type of space" narrows the suggestions for event and venue
        "spaces": [{"value": key, "label": s.get("label", key),
                    "families": list(s.get("families") or []),
                    "venues": list(s.get("venues") or [])} for key, s in k.spaces.items()],
        "venues": dict(k.venues),
        "activities": {key: a.label for key, a in k.activities.items()},
        "traditions": {key: t.label for key, t in k.traditions.items()},
    }


@router.get("/explorations/{exploration_id}/why/{element}")
def why(exploration_id: str, element: str) -> dict:
    """Provenance for one decision: "why did the system add (or forbid) a mandap?"

    Answers from the stored trace only — the semantic reading, the programme, the
    invariants, the critic findings and the final prompts — never by re-running."""
    from app.semantics.knowledge import load_knowledge
    rec = _record_or_404(exploration_id)
    sem = rec.semantic
    if sem is None:
        raise HTTPException(409, "this exploration predates semantic tracing")
    k = load_knowledge()
    hits = k.element_index.find(element.replace("_", " "))
    key = hits[0].key if hits else element
    el = sem.profile.element(key)
    zones = [z.model_dump(mode="json") for z in sem.programme
             if z.key == key or (k.elements.get(key) and k.elements[key].zone
                                 and k.elements[key].zone.key == z.key)]
    mentions = []
    for cid, p in rec.arch_prompts.items():
        found = [m.phrase for m in k.element_index.find(p.positive_prompt)
                 if m.key == key and not m.negated]
        if found:
            mentions.append({"concept_id": cid, "phrases": sorted(set(found))})
    findings = [
        {"concept_id": c.concept_id, "code": f.code, "statement": f.statement}
        for c in rec.all_concepts() if c.evaluation
        for f in c.evaluation.all_findings() if key in f.statement.lower().replace(" ", "_")
        or any(key in (e.excerpt or "").lower().replace(" ", "_") for e in f.evidence)
    ]
    return {
        "element": key,
        "decision": el.model_dump(mode="json") if el else None,
        "neutral": el is None,
        "explicitly_requested": key in sem.explicit_requests,
        "programme_zones": zones,
        "in_final_prompts": mentions,
        "critic_findings": findings,
        "reasoner_overrides": [o for o in sem.reasoner.overridden if key in o],
    }


@router.post("/explorations", status_code=202)
def create_exploration(req: BriefRequest, background: BackgroundTasks) -> dict:
    c = get_container()
    seed = req.seed if req.seed is not None else c.settings.engine_seed
    typology = Typology.GENERIC_SPATIAL
    if req.project_type:
        try:
            typology = Typology(req.project_type)
        except ValueError:
            typology = Typology.GENERIC_SPATIAL
    def _enum(cls, raw, fallback):
        """An unrecognised value falls back rather than 422-ing: a new tradition in
        the UI must never be able to take the engine down."""
        try:
            return cls(raw) if raw else fallback
        except ValueError:
            return fallback

    brief = DesignBrief(
        brief_id=new_id("bf"),
        raw_text=" ".join(filter(None, [req.brief, req.constraints])),
        typology=typology,
        event_type=_enum(EventType, req.event_type, EventType.GENERIC_EVENT),
        event_type_text=(req.event_type or "").strip() or None,
        tradition=_enum(Tradition, req.tradition, Tradition.UNSPECIFIED),
        venue_type=_enum(VenueType, req.venue_type, VenueType.UNSPECIFIED),
        # a venue beyond the original five is kept as text rather than dropped
        venue_text=(req.venue_type if req.venue_type and
                    _enum(VenueType, req.venue_type, None) is None else None),
        location=req.location, dimensions_text=req.dimensions,
        budget_text=req.budget, constraints_text=req.constraints,
    )
    rec_id = None

    injection = None
    if req.reference and req.reference.references:
        from app.domain.reference import ReferencePreset, ReferenceRequest, ReferenceSelector
        rr = ReferenceRequest(
            references=[ReferenceSelector(query=q) for q in req.reference.references],
            influence=req.reference.influence,
            preset=ReferencePreset(req.reference.preset),
            synthesis=req.reference.synthesis,
        )
        outcome = c.references.build(rr, None, seed=seed)
        if not outcome.ok:
            raise HTTPException(422, "Ambiguous reference — resolve it before generating.")
        injection = outcome.injection

    # ── optional trend discovery ────────────────────────────────────────────
    trend_result = None
    if req.trend and req.trend.mode != "OFF":
        from app.creative.program import build_program
        from app.domain.trend import TrendDiscoveryRequest, TrendDomain, TrendMode
        program = build_program(c.ontology, brief)
        if req.trend.result_id:
            trend_result = c.store.get_trend(req.trend.result_id)
        if trend_result is None:
            tr = TrendDiscoveryRequest(
                mode=TrendMode(req.trend.mode),
                domains=[TrendDomain(d) for d in req.trend.domains],
                max_selected=req.trend.max_selected, region=req.location, seed=seed)
            trend_result = c.trends.discover(program, brief.raw_text, tr)
            c.store.put_trend(trend_result)
        if injection is None:
            injection = c.trends.injection_for(
                trend_result, influence=req.trend.influence,
                candidate_ids=req.trend.candidate_ids or None, seed=seed)

    # create a placeholder synchronously so the UI can poll immediately
    from app.core.ids import deterministic_id
    rec_id = deterministic_id("ex", brief.brief_id, str(seed), str(req.k),
                              *([injection.injection_id] if injection else []))

    def _snapshot() -> None:
        """Write the run to the session archive as it currently stands.

        The store holds the live record by reference, so this sees concepts the
        moment stage 12 selects them and each one's prose the moment stage 14b
        writes it. Serialising a record another thread is mutating can raise; a
        failed tick is simply skipped, and the next one — or the final save —
        supersedes it. Archiving must never disturb the run it is watching.
        """
        rec = c.store.get(rec_id)
        if rec is None:
            return
        try:
            from app.api.serializers import concept_detail, exploration_payload
            _sessions.save(
                rec.exploration_id,
                exploration_payload(c.ontology, rec),
                {x.concept_id: concept_detail(c.ontology, rec, x) for x in rec.concepts},
            )
        except Exception as exc:                       # pragma: no cover
            elog.warn(f"session snapshot skipped ({type(exc).__name__}) — run unaffected")

    def _run():
        # Synthesis is minutes per concept. Snapshotting on a timer is what lets the
        # UI show concept 1 the moment it is written instead of after all k of them,
        # and what lets a reloaded page — or a restarted backend — find the run again.
        stop = threading.Event()

        def _watch() -> None:
            while not stop.wait(4.0):
                _snapshot()

        watcher = threading.Thread(target=_watch, name=f"archive:{rec_id}", daemon=True)
        watcher.start()
        try:
            with _lock:
                c.pipeline.run(brief, k=req.k, seed=seed, injection=injection,
                               trend_result=trend_result)
        finally:
            stop.set()
            watcher.join(timeout=5.0)
            _snapshot()          # authoritative: the completed run, or the failed one

    background.add_task(_run)
    return {"exploration_id": rec_id, "status": "RUNNING", "seed": seed, "k": req.k,
            "reference": bool(injection), "trend": bool(trend_result)}


@router.get("/sessions")
def list_sessions() -> dict:
    """Past runs, newest first, numbered oldest-first so Session 1 stays Session 1.

    Read from disk rather than from the store: the store is in-memory and empties on
    every restart, which is exactly the history this endpoint exists to keep.
    """
    return {"sessions": _sessions.list()}


@router.get("/sessions/{exploration_id}")
def get_session(exploration_id: str) -> dict:
    doc = _sessions.get(exploration_id)
    if doc is None:
        raise HTTPException(404, f"session {exploration_id} not found")
    return doc["exploration"]


@router.get("/sessions/{exploration_id}/concepts/{concept_id}")
def get_session_concept(exploration_id: str, concept_id: str) -> dict:
    doc = _sessions.get(exploration_id)
    if doc is None:
        raise HTTPException(404, f"session {exploration_id} not found")
    detail = (doc.get("concepts") or {}).get(concept_id)
    if detail is None:
        raise HTTPException(404, f"concept {concept_id} not in session {exploration_id}")
    return detail


# There is deliberately no delete route. Sessions are the only record of a run that
# survives a restart, and a stray click on a delete control already destroyed one.
# Removing a session is a filesystem operation on backend/.sessions/, on purpose.


@router.get("/explorations")
def list_explorations() -> dict:
    store = get_container().store
    out = []
    for eid in store.list_ids():
        rec = store.get(eid)
        out.append({"exploration_id": eid, "status": rec.status,
                    "brief": rec.brief.raw_text[:90], "seed": rec.seed,
                    "concepts": len(rec.concepts)})
    return {"explorations": out}


@router.get("/explorations/{exploration_id}")
def get_exploration(exploration_id: str) -> dict:
    c = get_container()
    return exploration_payload(c.ontology, _record_or_404(exploration_id))


@router.get("/explorations/{exploration_id}/concepts")
def get_concepts(exploration_id: str) -> dict:
    c = get_container()
    rec = _record_or_404(exploration_id)
    from app.api.serializers import concept_summary
    return {"concepts": [concept_summary(c.ontology, rec, x) for x in rec.concepts]}


@router.get("/explorations/{exploration_id}/comparison")
def get_comparison(exploration_id: str) -> dict:
    c = get_container()
    return {"rows": comparison_rows(c.ontology, _record_or_404(exploration_id))}


@router.get("/explorations/{exploration_id}/debug")
def get_debug(exploration_id: str) -> dict:
    c = get_container()
    return debug_payload(c.ontology, _record_or_404(exploration_id))


@router.get("/explorations/{exploration_id}/synthesis-debug")
def synthesis_debug(exploration_id: str) -> dict:
    """The §25 chain: DNA -> model input -> raw output -> validated -> repairs ->
    compiled prompt -> hash.

    This exists to answer one question precisely: did the ENGINE choose a bad concept,
    did the MODEL describe it badly, or did the COMPILER lose the architecture?
    """
    c = get_container()
    rec = c.store.get(exploration_id)
    if rec is None:
        raise HTTPException(404, "unknown exploration")
    rows = []
    for dna in rec.concepts:
        trace = rec.synthesis_traces.get(dna.concept_id)
        sc = rec.structured.get(dna.concept_id)
        ap = rec.arch_prompts.get(dna.concept_id)
        v = rec.validations.get(dna.concept_id)
        rows.append({
            "concept_id": dna.concept_id,
            "role": dna.role.value,
            "engine": {
                "title": dna.phenotype.title,
                "dna": {r["facet"]: r["label"] for r in concept_dna_rows(c.ontology, dna)},
            },
            "model_input": trace.prompt if trace else "",
            "raw_output": trace.raw_output if trace else None,
            "validated": sc.model_dump(mode="json") if sc else None,
            "validation": v.model_dump(mode="json") if v else None,
            "repairs": {
                "repaired": trace.repaired if trace else False,
                "attempts": trace.attempts if trace else 0,
                "instruction": trace.repair_instruction if trace else "",
                "before": trace.findings_before if trace else [],
                "after": trace.findings_after if trace else [],
            },
            "compiled_prompt": ap.positive_prompt if ap else "",
            "prompt_sections": ([{"name": s.name, "source": s.source}
                                 for s in ap.sections] if ap else []),
            "prompt_hash": ap.prompt_hash if ap else "",
            "error": trace.error if trace else "",
            "duration_ms": trace.duration_ms if trace else 0,
        })
    return {
        "enabled": bool(rec.synthesis_traces),
        "provider": next((t.provider for t in rec.synthesis_traces.values()), ""),
        "model": next((t.model for t in rec.synthesis_traces.values()), ""),
        "calls": rec.synthesis_calls, "repairs": rec.synthesis_repairs,
        "valid": sum(1 for v in rec.validations.values() if v.passed),
        "concepts": rows,
    }


@router.get("/explorations/{exploration_id}/reference-debug")
def reference_debug(exploration_id: str) -> dict:
    """Answers two separate questions: did the system understand the reference, and did
    that understanding actually reach the concepts?"""
    c = get_container()
    rec = _record_or_404(exploration_id)
    inj = rec.injection
    if inj is None:
        return {"reference_mode": False}
    from app.api.routes_references import _dna_payload, _principle_payload
    return {
        "reference_mode": True,
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
        "allocation": [
            {"index": n.index, "role": n.role.value,
             "principles": list(n.injected_principles),
             "is_reference": any(pid.startswith("refprin_") for pid in n.injected_principles)}
            for n in rec.niches
        ],
        "per_concept": [
            {"concept_id": x.concept_id, "title": x.phenotype.title, "role": x.role.value,
             **(x.reference_context.model_dump(mode="json") if x.reference_context else {})}
            for x in rec.concepts
        ],
        "portfolio": _portfolio_reference_summary(rec),
    }


def _portfolio_reference_summary(rec) -> dict:
    ctxs = [x.reference_context for x in rec.concepts if x.reference_context]
    if not ctxs:
        return {}
    ts = [c.transformation for c in ctxs]
    above = sum(1 for c in ctxs if c.influence_measured >= 0.25)
    dims = {d.value for c in ctxs for d in c.dimensions}
    return {
        "mean_transformation": round(sum(ts) / len(ts), 4),
        "concepts_with_influence": above,
        "concepts_total": len(ctxs),
        "distinct_dimensions": sorted(dims),
        "any_surface_leak": any(c.surface_leaks for c in ctxs),
        "meets_R_REF_11": (sum(ts) / len(ts)) >= 0.60 and above >= 7,
    }


@router.get("/explorations/{exploration_id}/trend-debug")
def trend_debug(exploration_id: str) -> dict:
    """plan → queries → candidates → scores → selection → which became references."""
    rec = _record_or_404(exploration_id)
    tr = rec.trend_result
    if tr is None:
        return {"trend_mode": False}
    from app.api.routes_trends import _result_payload
    payload = _result_payload(tr)
    inj = rec.injection
    payload["became_references"] = (
        [{"reference_id": d.identity.reference_id, "display_name": d.identity.display_name,
          "traits": len(d.traits)} for d in inj.reference_dnas] if inj else [])
    payload["principles"] = (
        [{"source_domain": p.source_domain, "dimension": p.provenance.dimension,
          "statement": p.statements[0] if p.statements else ""} for p in inj.principles]
        if inj else [])
    return payload


@router.get("/concepts/{concept_id}")
def get_concept(concept_id: str) -> dict:
    c = get_container()
    rec, dna = _find_concept(concept_id)
    return concept_detail(c.ontology, rec, dna)


@router.get("/concepts/{concept_id}/prompt")
def get_prompt(concept_id: str, view: str = "HERO", dialect: str = "GENERIC") -> dict:
    c = get_container()
    rec, dna = _find_concept(concept_id)
    cached = rec.prompts.get(concept_id)
    if cached and view == cached.view_role.value and dialect == cached.dialect:
        return cached.model_dump(mode="json")
    pc = compile_prompt(c.ontology, dna, rec.program, rec.scenes.get(concept_id),
                        rec.antibrief, ViewRole(view), dialect, rec.seed)
    return pc.model_dump(mode="json")


def _derive_concept(rec, parent: ConceptDNA, genotype, operator: str, origin: str):
    """Shared tail for mutate/combine: re-express, re-evaluate, recompile, store."""
    c = get_container()
    ont = c.ontology
    titles = [x.phenotype.title for x in rec.concepts]
    phenotype, fidelity, calls = synthesise_phenotype(
        c.llm, ont, rec.program, genotype, role=parent.role, seed=rec.seed + 991,
        sibling_titles=titles,
    )
    new_id_ = new_id("cn")
    dna = parent.model_copy(update={
        "concept_id": new_id_, "genotype": genotype, "phenotype": phenotype,
        "lineage": Lineage(parent_ids=[parent.concept_id], operator=operator,
                           generation=parent.lineage.generation + 1, origin=origin),
        "status": "DRAFT", "evaluation": None,
    })
    from app.scene.build import build_scene_graph
    scene, _ = build_scene_graph(c.llm, ont, new_id_, genotype, rec.program, rec.seed)
    ev, _ = evaluate(c.llm, ont, dna, rec.program, scene, fidelity, rec.seed,
                     use_llm=c.pipeline.use_llm_critics)
    dna = dna.model_copy(update={"evaluation": ev, "status": "EVALUATED",
                                 "scene_graph_id": scene.scene_graph_id})
    rec.scenes[new_id_] = scene
    pc = compile_prompt(ont, dna, rec.program, scene, rec.antibrief, ViewRole.HERO, "GENERIC", rec.seed)
    rec.prompts[new_id_] = pc
    dna = dna.model_copy(update={"prompt_compilation_ids": [pc.prompt_id]})
    rec.concepts.append(dna)
    c.store.put(rec)
    distance = genotype_distance(ont, parent.genotype, genotype)
    return {"concept": concept_detail(ont, rec, dna),
            "parent_id": parent.concept_id,
            "distance_from_parent": round(distance, 3), "operator": operator}


@router.post("/concepts/{concept_id}/mutate")
def mutate(concept_id: str, req: MutateRequest) -> dict:
    c = get_container()
    rec, parent = _find_concept(concept_id)
    rng = SeededRandom(rec.seed, "mutate", concept_id, req.intent)
    chain = {
        "unexpected": ["reinterpret", "invert"],
        "practical": ["attenuate", "material_substitute"],
        "similar": ["material_substitute", "transpose"],
        "opposite": ["invert", "reinterpret"],
    }.get(req.intent, ["reinterpret"])
    if req.operator:
        chain = [req.operator]
    pinned = set(req.pin)
    for op_id in chain:
        out = apply_operator(op_id, c.ontology, rec.space, parent.genotype, rng, pinned,
                             magnitude=0.8 if req.intent in ("unexpected", "opposite") else 0.3)
        if out.status == "APPLIED" and out.genotype is not None:
            return _derive_concept(rec, parent, out.genotype, op_id, "MUTATED")
    raise HTTPException(422, f"no operator in {chain} could be applied "
                             f"(pinned={sorted(pinned)})")


@router.post("/concepts/{concept_id}/combine")
def combine(concept_id: str, req: CombineRequest) -> dict:
    c = get_container()
    rec, a = _find_concept(concept_id)
    _, b = _find_concept(req.other_id)
    rng = SeededRandom(rec.seed, "combine", concept_id, req.other_id)
    out = op_hybridise(c.ontology, rec.space, a.genotype, b.genotype, rng, set())
    if out.status != "APPLIED" or out.genotype is None:
        raise HTTPException(422, f"cannot combine: {out.note}")
    return _derive_concept(rec, a, out.genotype, "hybridise", "HYBRIDISED")


@router.post("/concepts/{concept_id}/rate")
def rate(concept_id: str, req: RateRequest) -> dict:
    c = get_container()
    rec, dna = _find_concept(concept_id)
    # feedback attaches to FACETS, not just the concept — the column V2 learning needs
    facets = {row["facet"]: row["label"] for row in
              __import__("app.api.serializers", fromlist=["concept_dna_rows"]).concept_dna_rows(c.ontology, dna)}
    c.store.add_feedback({"concept_id": concept_id, "kind": req.kind,
                          "reason_code": req.reason_code, "note": req.note,
                          "facet_attribution": facets})
    return {"ok": True, "recorded": req.kind, "facets_attributed": len(facets)}
