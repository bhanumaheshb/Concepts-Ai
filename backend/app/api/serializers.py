"""Response shaping. Keeps the API surface stable and independent of internal models."""
from __future__ import annotations

from typing import Any

from app.creative.pipeline import ExplorationRecord
from app.domain.concept import ConceptDNA
from app.ontology.graph import Ontology


def label_ref(ont: Ontology, ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    node = ont.nodes.get(ref)
    return {"ref": ref, "label": node.label if node else ref.split(":")[-1].replace("_", " "),
            "desc": node.desc if node else ""}


def concept_dna_rows(ont: Ontology, dna: ConceptDNA) -> list[dict[str, Any]]:
    g = dna.genotype
    rows = [
        ("Thesis archetype", label_ref(ont, g.thesis_archetype.value)),
        ("Architectural language", label_ref(ont, g.architectural_language.value)),
        ("Geometry", label_ref(ont, g.geometry.system)),
        ("Structural logic", label_ref(ont, g.structural_logic.value)),
        ("Tectonic logic", label_ref(ont, g.tectonic_logic.value)),
        ("Occupation staging", label_ref(ont, g.occupation_staging.value)),
        ("Lighting philosophy", label_ref(ont, g.lighting_philosophy.value)),
        ("Site relationship", label_ref(ont, g.site_relationship.value)),
        ("Scale strategy", label_ref(ont, g.scale_strategy.value)),
        ("Emotional register", label_ref(ont, g.emotional_register.value)),
    ]
    out = [{"facet": name, **(val or {})} for name, val in rows]
    out.append({"facet": "Material palette", "ref": "", "label": ", ".join(
        f"{(ont.nodes[m.material].label if m.material in ont.nodes else m.material)}"
        f" ({m.role.value.lower()} {int(m.share * 100)}%)" for m in g.material_palette), "desc": ""})
    out.append({"facet": "Spatial narrative", "ref": "", "label": " → ".join(
        (ont.nodes[s].label if s in ont.nodes else s) for s in g.spatial_narrative), "desc": ""})
    out.append({"facet": "Cultural lineage", "ref": "", "label": ", ".join(
        f"{ont.label(c.ref)} (abstraction {c.abstraction})" for c in g.cultural_lineage) or "—", "desc": ""})
    out.append({"facet": "Technology", "ref": "", "label": ", ".join(
        t.split(":")[-1].replace("_", " ") for t in g.technology) or "—", "desc": ""})
    out.append({"facet": "Anti-attributes", "ref": "", "label": ", ".join(
        ont.label(a) for a in g.anti_attributes) or "—", "desc": ""})
    return out


def _synthesis_card(rec: ExplorationRecord, dna: ConceptDNA) -> dict[str, Any] | None:
    """Card-level synthesis fields. None when the synthesis layer is disabled."""
    sc = rec.structured.get(dna.concept_id)
    if sc is None:
        trace = rec.synthesis_traces.get(dna.concept_id)
        return {"available": False, "error": trace.error if trace else ""} if trace else None
    v = rec.validations.get(dna.concept_id)
    return {
        "available": True,
        "concept_title": sc.concept_title,
        "thesis": sc.concept_thesis,
        "spatial_story": sc.design_story,
        "architectural_language": sc.architectural_language,
        "materials": sc.materials.primary,
        "materials_secondary": sc.materials.secondary,
        "lighting": sc.lighting.colour_temperature or ", ".join(sc.lighting.lighting_sources),
        "program": sc.program.focal_space_label or sc.program.focal_space[:60],
        "atmosphere": sc.atmosphere,
        "source": sc.source, "model": sc.model,
        "repaired": sc.repaired, "attempts": sc.attempts,
        "valid": bool(v.passed) if v else None,
        "findings": len(v.findings) if v else 0,
    }


def concept_summary(ont: Ontology, rec: ExplorationRecord, dna: ConceptDNA) -> dict[str, Any]:
    ev = dna.evaluation
    prompt = rec.prompts.get(dna.concept_id)
    niche = next((n for n in rec.niches if n.niche_id == dna.niche_id), None)
    g = dna.genotype
    # display index is the PORTFOLIO position, not the pool slot the niche came from
    try:
        display_index = rec.concepts.index(dna) + 1
    except ValueError:
        display_index = len(rec.concepts) + 1
    return {
        "concept_id": dna.concept_id,
        "index": display_index,
        "pool_slot": dna.niche_index,
        # the synthesised title/thesis take precedence on the card when present;
        # the deterministic phenotype remains the fallback and the source of truth
        # for anything the model failed to produce.
        "title": (rec.structured[dna.concept_id].concept_title
                  if dna.concept_id in rec.structured
                  and rec.structured[dna.concept_id].concept_title
                  else dna.phenotype.title),
        "engine_title": dna.phenotype.title,
        "synthesis": _synthesis_card(rec, dna),
        "one_line": dna.phenotype.one_line,
        "signature_read": dna.phenotype.signature_read,
        "role": dna.role.value,
        "niche": {
            "niche_id": dna.niche_id,
            "role": dna.role.value,
            "band": list(niche.target_band) if niche else [0, 1],
            "distance_to_canonical": round(niche.distance_to_canonical, 3) if niche else 0.0,
            "forbidden": [ont.label(f) for f in (niche.forbidden if niche else [])][:6],
            "score_breakdown": niche.score_breakdown if niche else {},
        },
        "principle": ({"id": dna.principle_id,
                       "source_domain": ont.principles[dna.principle_id].source_domain,
                       "statements": ont.principles[dna.principle_id].statements}
                      if dna.principle_id and dna.principle_id in ont.principles else None),
        "headline_dna": {
            "architectural_language": ont.label(g.architectural_language.value),
            "geometry": ont.label(g.geometry.system),
            "structural_logic": ont.label(g.structural_logic.value),
            "material": ont.label(g.primary_material().material),
            "spatial_narrative": " → ".join(ont.label(s) for s in g.spatial_narrative),
            "emotional_register": ont.label(g.emotional_register.value),
        },
        "scores": {
            "novelty": round(ev.novelty.vs_platform, 3) if ev else None,
            "quality": round(ev.quality_q, 3) if ev else None,
            "diversity": round(rec.matrix.min_distance_for(dna.concept_id), 3) if rec.matrix else None,
            "alignment": {"score": ev.alignment.score, "pass": ev.alignment.passed} if ev else None,
            "coherence": {"score": ev.coherence.score, "pass": ev.coherence.passed} if ev else None,
            "feasibility": {"score": ev.feasibility.score, "pass": ev.feasibility.passed} if ev else None,
            "cultural": {"score": ev.cultural.score, "pass": ev.cultural.passed} if ev else None,
            "gate_passed": ev.gate_passed if ev else False,
        },
        "reference": _reference_summary(ont, rec, dna),
        "prompt_ready": prompt is not None,
        "prompt_hash": prompt.prompt_hash[:12] if prompt else None,
        "status": dna.status,
        "lineage": dna.lineage.model_dump(mode="json"),
    }


def _reference_summary(ont: Ontology, rec: ExplorationRecord, dna: ConceptDNA) -> dict[str, Any] | None:
    ctx = dna.reference_context
    if ctx is None:
        return None
    inj = rec.injection
    by_id = {p.id: p for p in (inj.principles if inj else [])}
    return {
        "influence": ctx.influence_measured,
        # the canonical is the deliberate literal interpretation: showing it a low
        # transformation number would be misleading (R-REF-10)
        "transformation": None if ctx.is_literal_slot else ctx.transformation,
        "is_literal": ctx.is_literal_slot,
        "channels": ctx.channels.model_dump(mode="json"),
        "surface_leaks": ctx.surface_leaks,
        "dimensions": [d.value for d in ctx.dimensions],
        "principles": [
            {"id": pid, "source_domain": by_id[pid].source_domain,
             "statement": by_id[pid].statements[0] if by_id[pid].statements else "",
             "dimension": by_id[pid].provenance.dimension,
             "abstraction": by_id[pid].provenance.abstraction,
             "reference_ids": list(by_id[pid].provenance.reference_ids)}
            for pid in ctx.injected_principle_ids if pid in by_id
        ],
        "chain": [
            {"reference_id": t.reference_id, "trait_id": t.trait_id,
             "dimension": t.dimension.value, "principle_id": t.principle_id,
             "source_domain": by_id[t.principle_id].source_domain if t.principle_id in by_id else "",
             "facet": t.facet_id, "value": t.value, "stuck": t.stuck}
            for t in ctx.trace
        ],
        "removed_tokens": (inj.blocked_tokens() if inj else []),
    }


def concept_detail(ont: Ontology, rec: ExplorationRecord, dna: ConceptDNA) -> dict[str, Any]:
    base = concept_summary(ont, rec, dna)
    scene = rec.scenes.get(dna.concept_id)
    prompt = rec.prompts.get(dna.concept_id)
    ev = dna.evaluation
    base.update({
        "design_thesis": dna.phenotype.design_thesis,
        "spatial_explanation": dna.phenotype.spatial_explanation,
        "material_explanation": dna.phenotype.material_explanation,
        "experience": dna.phenotype.experience_narrative,
        "what_it_is_not": dna.phenotype.what_it_is_not,
        "reconciliation_thesis": dna.phenotype.reconciliation_thesis,
        "rationale_chain": [r.model_dump(mode="json") for r in dna.phenotype.rationale_chain],
        "precedent_notes": [p.model_dump(mode="json") for p in dna.phenotype.precedent_notes],
        "visual_direction": dna.phenotype.visual_direction.model_dump(mode="json"),
        "concept_dna": concept_dna_rows(ont, dna),
        "genotype": dna.genotype.model_dump(mode="json"),
        "scene_graph": scene.model_dump(mode="json") if scene else None,
        "prompt": prompt.model_dump(mode="json") if prompt else None,
        "structured_concept": (rec.structured[dna.concept_id].model_dump(mode="json")
                               if dna.concept_id in rec.structured else None),
        "architectural_prompt": (rec.arch_prompts[dna.concept_id].model_dump(mode="json")
                                 if dna.concept_id in rec.arch_prompts else None),
        # The shot list: one prompt per area, all sharing one `shared_signature`.
        "view_prompts": [v.model_dump(mode="json")
                         for v in rec.view_prompts.get(dna.concept_id, [])],
        "validation": (rec.validations[dna.concept_id].model_dump(mode="json")
                       if dna.concept_id in rec.validations else None),
        "findings": [
            {"critic": r.critic.value, "code": f.code, "severity": f.severity.value,
             "statement": f.statement,
             "evidence": [e.model_dump(mode="json") for e in f.evidence]}
            for r in (ev.results() if ev else []) for f in r.findings
        ],
        "distances": ([
            {"other_id": oid,
             "other_title": next((c.phenotype.title for c in rec.concepts if c.concept_id == oid), oid),
             "distance": rec.matrix.distances[rec.matrix.concept_ids.index(dna.concept_id)][j],
             "drivers": next((d.top_facets for d in rec.matrix.drivers
                              if {d.a, d.b} == {dna.concept_id, oid}), [])}
            for j, oid in enumerate(rec.matrix.concept_ids) if oid != dna.concept_id
        ] if rec.matrix and dna.concept_id in rec.matrix.concept_ids else []),
    })
    return base


def exploration_payload(ont: Ontology, rec: ExplorationRecord) -> dict[str, Any]:
    return {
        "exploration_id": rec.exploration_id,
        "status": rec.status,
        "error": rec.error,
        "seed": rec.seed,
        "k": rec.k,
        "brief": rec.brief.model_dump(mode="json"),
        "stages": rec.stage_status(),
        "degraded": rec.degraded,
        "llm_calls": rec.llm_calls,
        "elapsed_ms": int(((rec.finished_at or 0) - rec.started_at) * 1000) if rec.finished_at else None,
        "versions": rec.versions.model_dump(mode="json"),
        "program": rec.program.model_dump(mode="json") if rec.program else None,
        "portfolio": {
            "curriculum_satisfied": rec.portfolio.curriculum_satisfied if rec.portfolio else None,
            "curriculum_gap": rec.portfolio.curriculum_gap if rec.portfolio else None,
            "selection_log": [s.model_dump(mode="json") for s in rec.portfolio.selection_log]
                             if rec.portfolio else [],
        },
        "diversity": {
            "vendi_score": rec.matrix.vendi_score if rec.matrix else None,
            "mean_pairwise": rec.matrix.mean_pairwise if rec.matrix else None,
            "min_pairwise": rec.matrix.min_pairwise if rec.matrix else None,
            "channels_used": rec.matrix.channels_used if rec.matrix else [],
            "concept_ids": rec.matrix.concept_ids if rec.matrix else [],
            "labels": [next((c.phenotype.title for c in rec.concepts if c.concept_id == cid), cid)
                       for cid in (rec.matrix.concept_ids if rec.matrix else [])],
            "distances": rec.matrix.distances if rec.matrix else [],
        },
        "concepts": [concept_summary(ont, rec, c) for c in rec.concepts],
        "reference_mode": rec.injection is not None,
        "reference_summary": (
            {"references": [d.identity.display_name for d in rec.injection.reference_dnas],
             "influence": rec.injection.influence.model_dump(mode="json"),
             "compatibility": (rec.injection.compatibility.verdict.value
                               if rec.injection.compatibility else None),
             "principles": len(rec.injection.principles)}
            if rec.injection else None),
    }


def debug_payload(ont: Ontology, rec: ExplorationRecord) -> dict[str, Any]:
    """Everything needed to answer 'why did the system produce this concept?'"""
    return {
        "exploration_id": rec.exploration_id,
        "brief": rec.brief.model_dump(mode="json"),
        "design_program": rec.program.model_dump(mode="json") if rec.program else None,
        "anti_brief": rec.antibrief.model_dump(mode="json") if rec.antibrief else None,
        "search_space": ({
            "space_id": rec.space.space_id,
            "effective_dimensionality": rec.space.effective_dimensionality,
            "relaxations_applied": rec.space.relaxations_applied,
            "domains": [{
                "facet": d.facet_id, "legal_count": len(d.legal),
                "legal": [ont.label(v.value) for v in d.legal],
                "excluded": [{"value": ont.label(e.value), "rule": e.rule_id, "reason": e.reason}
                             for e in d.excluded],
            } for d in rec.space.domains],
        } if rec.space else None),
        "niches": [{
            "index": n.index, "role": n.role.value, "band": list(n.target_band),
            "distance_to_canonical": round(n.distance_to_canonical, 3),
            "forbidden": [ont.label(f) for f in n.forbidden],
            "principles": n.injected_principles,
            "domain_override": {k: [ont.label(x) for x in v] for k, v in n.domain_override.items()},
            "score_breakdown": n.score_breakdown,
        } for n in rec.niches],
        "principles_used": sorted({p for n in rec.niches for p in n.injected_principles}),
        "genotypes": [{"concept_id": c.concept_id, "title": c.phenotype.title,
                       "genotype": c.genotype.model_dump(mode="json")}
                      for c in rec.all_concepts()],
        "critics": [{
            "concept_id": c.concept_id, "title": c.phenotype.title,
            "gate_passed": c.evaluation.gate_passed if c.evaluation else None,
            "quality_q": c.evaluation.quality_q if c.evaluation else None,
            "results": [r.model_dump(mode="json") for r in (c.evaluation.results() if c.evaluation else [])],
        } for c in rec.all_concepts()],
        "repairs": [r.model_dump(mode="json") for r in rec.repairs],
        "rejected": [{"concept_id": c.concept_id, "title": c.phenotype.title,
                      "reason": c.rejection.model_dump(mode="json") if c.rejection else None}
                     for c in rec.rejected],
        "diversity_matrix": {
            "ids": rec.matrix.concept_ids if rec.matrix else [],
            "labels": [next((c.phenotype.title for c in rec.concepts if c.concept_id == cid), cid)
                       for cid in (rec.matrix.concept_ids if rec.matrix else [])],
            "distances": rec.matrix.distances if rec.matrix else [],
            "drivers": [d.model_dump(mode="json") for d in (rec.matrix.drivers if rec.matrix else [])],
            "vendi_score": rec.matrix.vendi_score if rec.matrix else None,
        },
        "portfolio": rec.portfolio.model_dump(mode="json") if rec.portfolio else None,
        "prompts": {cid: p.model_dump(mode="json") for cid, p in rec.prompts.items()},
        "synthesis": {
            "enabled": bool(rec.synthesis_traces),
            "provider": next((t.provider for t in rec.synthesis_traces.values()), ""),
            "model": next((t.model for t in rec.synthesis_traces.values()), ""),
            "synthesised": len(rec.structured),
            "valid": sum(1 for v in rec.validations.values() if v.passed),
            "calls": rec.synthesis_calls,
            "repairs": rec.synthesis_repairs,
            "failed": [cid for cid, t in rec.synthesis_traces.items() if t.error],
        },
        "stage_runs": [s.model_dump(mode="json") for s in rec.stage_runs],
    }


def comparison_rows(ont: Ontology, rec: ExplorationRecord) -> list[dict[str, Any]]:
    rows = []
    for i, c in enumerate(rec.concepts):
        g = c.genotype
        ev = c.evaluation
        rows.append({
            "index": i + 1, "concept_id": c.concept_id, "title": c.phenotype.title,
            "niche": c.role.value,
            "architecture": ont.label(g.architectural_language.value),
            "geometry": ont.label(g.geometry.system),
            "structure": ont.label(g.structural_logic.value),
            "material": ont.label(g.primary_material().material),
            "narrative": " → ".join(ont.label(s) for s in g.spatial_narrative),
            "principle": (ont.principles[c.principle_id].source_domain
                          if c.principle_id and c.principle_id in ont.principles else "—"),
            "novelty": round(ev.novelty.vs_platform, 2) if ev else None,
            "diversity": round(rec.matrix.min_distance_for(c.concept_id), 2) if rec.matrix else None,
            "alignment": ev.alignment.passed if ev else None,
            "coherence": ev.coherence.passed if ev else None,
            "feasibility": ev.feasibility.passed if ev else None,
            "cultural": ev.cultural.passed if ev else None,
        })
    return rows
