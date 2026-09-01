"""Repair.

A failing concept is a genotype with a specific defect, not a bad idea. Repair fixes
the defect at the coordinate that caused it and preserves everything that made the
concept worth having.

Three guards, in order of how often they matter:
  1. sibling collapse — a repair that fixes the finding but pulls the concept into a
     sibling is rejected (repair drags concepts toward the feasible centre, which is
     exactly where their siblings already are);
  2. identity preservation — the three identity facets never change;
  3. budget — repairs draw from the exploration's synthesis-call budget.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.critics import codes
from app.critics.runner import evaluate
from app.diversity.metric import D_MIN, genotype_distance
from app.domain.brief import DesignProgram
from app.domain.common import CriticName, IDENTITY_FACETS, Severity
from app.domain.concept import ConceptDNA, Lineage
from app.domain.evaluation import CriticFinding, EvaluationResult
from app.domain.genotype import ConceptGenotype
from app.domain.scene import SceneGraph
from app.domain.space import CreativeSearchSpace
from app.mutation.operators import apply_operator
from app.ontology.graph import Ontology

# finding code -> operators to try, in order
REPAIR_ROUTE: dict[str, list[str]] = {
    codes.FEAS_MATERIAL_STRUCTURE_INCOMPATIBLE: ["material_substitute", "transpose"],
    codes.FEAS_SPAN_EXCEEDED: ["material_substitute", "transpose"],
    codes.FEAS_COST_BAND: ["attenuate", "material_substitute"],
    codes.FEAS_BUILD_DAYS: ["attenuate", "material_substitute"],
    codes.FEAS_CLIMATE_INCOMPATIBLE: ["material_substitute", "transpose"],
    codes.COH_EXCLUDES_VIOLATION: ["transpose", "invert"],
    codes.COH_REQUIRES_UNMET: ["__closure__"],
    codes.COH_TENSION_UNRECONCILED: ["__re_express__"],
    codes.COH_FIDELITY: ["__re_express__"],
    codes.COH_SOURCE_NAMED: ["__re_express__"],
    codes.ALIGN_CAPACITY_SHORT: ["scale_up"],
    codes.ALIGN_AREA_OVERFLOW: ["attenuate"],
    codes.ALIGN_ZONE_MISSING: ["__re_express__"],
    codes.ALIGN_SCHEDULE_EXCEEDED: ["attenuate", "material_substitute"],
    codes.CULT_ABSTRACTION_FLOOR: ["abstract"],
    # ── reference routes ────────────────────────────────────────────────────
    # None of these drops the reference: `abstract` raises the abstraction of the
    # borrowed material, `reinterpret` resamples form while pinning identity, and
    # `__re_express__` fixes prose without touching the genotype at all.
    "REF_SURFACE_LEAK": ["__re_express__"],
    "REF_LITERAL_OCCUPANCY": ["abstract", "transpose"],
    "REF_UNDER_TRANSFORMED": ["reinterpret", "transpose"],
}

# facet -> critics whose result can change when that facet moves
FACET_CRITICS: dict[str, set[CriticName]] = {
    "material_palette": {CriticName.FEASIBILITY, CriticName.COHERENCE, CriticName.CULTURAL},
    "structural_logic": {CriticName.FEASIBILITY, CriticName.COHERENCE},
    "geometry_system": {CriticName.FEASIBILITY, CriticName.COHERENCE, CriticName.ALIGNMENT},
    "scale_strategy": {CriticName.ALIGNMENT, CriticName.FEASIBILITY},
    "occupation_staging": {CriticName.ALIGNMENT, CriticName.CULTURAL},
    "tectonic_logic": {CriticName.FEASIBILITY, CriticName.COHERENCE},
    "site_relationship": {CriticName.ALIGNMENT, CriticName.FEASIBILITY},
    "lighting_philosophy": {CriticName.COHERENCE},
    "cultural_lineage": {CriticName.CULTURAL, CriticName.COHERENCE},
    "architectural_language": {CriticName.COHERENCE, CriticName.CULTURAL},
}


@dataclass
class ConceptIdentity:
    thesis_archetype: str
    spatial_narrative: list[str]
    emotional_register: str
    title: str
    signature_read: str

    @staticmethod
    def of(dna: ConceptDNA) -> "ConceptIdentity":
        return ConceptIdentity(
            thesis_archetype=dna.genotype.thesis_archetype.value,
            spatial_narrative=list(dna.genotype.spatial_narrative),
            emotional_register=dna.genotype.emotional_register.value,
            title=dna.phenotype.title,
            signature_read=dna.phenotype.signature_read,
        )

    def holds_for(self, g: ConceptGenotype) -> bool:
        return (g.thesis_archetype.value == self.thesis_archetype
                and list(g.spatial_narrative) == self.spatial_narrative
                and g.emotional_register.value == self.emotional_register)


@dataclass
class RepairOutcome:
    status: str                    # REPAIRED | HUMAN_REVIEW | ABANDONED | NO_FINDINGS
    dna: ConceptDNA | None
    operator: str | None
    finding_code: str | None
    note: str
    llm_calls: int = 0


def critics_to_rerun(failed: CriticName, touched: list[str]) -> set[CriticName]:
    """COHERENCE is always included: any genotype edit can break an excludes or
    requires relation."""
    out = {failed, CriticName.COHERENCE}
    for f in touched:
        out |= FACET_CRITICS.get(f, set())
    return out


def _worst(findings: list[CriticFinding]) -> CriticFinding | None:
    order = {Severity.BLOCKER: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
    blocking = [f for f in findings if f.severity in (Severity.BLOCKER, Severity.MAJOR)]
    if not blocking:
        return None
    return sorted(blocking, key=lambda f: order[f.severity])[0]


def _critic_of(code: str) -> CriticName:
    if code.startswith("REF_"):
        return CriticName.ORIGINALITY
    if code.startswith("ALIGN"):
        return CriticName.ALIGNMENT
    if code.startswith("COH"):
        return CriticName.COHERENCE
    if code.startswith("FEAS"):
        return CriticName.FEASIBILITY
    return CriticName.CULTURAL


def repair_concept(
    llm, ont: Ontology, space: CreativeSearchSpace, program: DesignProgram,
    dna: ConceptDNA, siblings: list[ConceptGenotype], scene: SceneGraph | None,
    resynthesise, rng, seed: int, max_attempts: int = 2, use_llm: bool = True,
) -> RepairOutcome:
    from app.space.csp import requires_closure

    identity = ConceptIdentity.of(dna)
    pinned = set(IDENTITY_FACETS)
    current = dna
    calls = 0

    for attempt in range(1, max_attempts + 1):
        findings = current.evaluation.all_findings() if current.evaluation else []
        target = _worst(findings)
        if target is None:
            return RepairOutcome("NO_FINDINGS", current, None, None, "nothing to repair", calls)
        if target.code in codes.NO_AUTO_REPAIR:
            return RepairOutcome("HUMAN_REVIEW", current, None, target.code,
                                 "cultural findings are never auto-repaired", calls)

        route = REPAIR_ROUTE.get(target.code, [])
        for op_id in route:
            if op_id == "__closure__":
                new_g = current.genotype.model_copy(
                    update={"technology": requires_closure(ont, current.genotype.all_refs())})
                touched: list[str] = ["technology"]
                note = "deterministic requires-closure"
            elif op_id == "__re_express__":
                new_g, touched, note = current.genotype, [], "re-express only"
            else:
                out = apply_operator(op_id, ont, space, current.genotype,
                                     rng.substream("rep", attempt, op_id), pinned, magnitude=0.3)
                if out.status != "APPLIED" or out.genotype is None:
                    continue
                new_g, touched, note = out.genotype, out.touched, out.note

            if not identity.holds_for(new_g):
                continue                                  # guard 2
            if siblings:
                if min(genotype_distance(ont, new_g, s) for s in siblings) < D_MIN:
                    continue                              # guard 1 — the one people forget

            phenotype, fidelity, c = resynthesise(
                new_g, preserve_title=identity.title, preserve_signature=identity.signature_read,
                fix_notes=[f"fix: {target.statement}"],
            )
            calls += c
            candidate = current.model_copy(update={
                "genotype": new_g, "phenotype": phenotype,
                "lineage": Lineage(parent_ids=[current.concept_id], operator=op_id,
                                   generation=current.lineage.generation + 1,
                                   pinned_facets=sorted(pinned), origin="REPAIRED"),
                "status": "REPAIRING",
            })
            only = critics_to_rerun(_critic_of(target.code), touched)
            ev, c2 = evaluate(llm, ont, candidate, program, scene, fidelity, seed,
                              novelty=current.evaluation.novelty.vs_platform if current.evaluation else 1.0,
                              only=only, previous=current.evaluation, use_llm=use_llm)
            calls += c2
            candidate = candidate.model_copy(update={"evaluation": ev})
            if ev.gate_passed:
                return RepairOutcome("REPAIRED", candidate.model_copy(update={"status": "EVALUATED"}),
                                     op_id, target.code, note, calls)
            current = candidate      # partial progress carries into the next attempt

    return RepairOutcome("ABANDONED", current, None, None, "repair_exhausted", calls)
