"""Deterministic checks. These run FIRST; a blocker here means no model call at all,
which is both cheaper and faster than asking a model to confirm arithmetic."""
from __future__ import annotations

from app.critics import codes
from app.domain.brief import DesignProgram
from app.domain.common import CriticName, Severity
from app.domain.concept import ConceptDNA
from app.domain.evaluation import CriticFinding, EvidenceSpan
from app.domain.scene import SceneGraph
from app.ontology.graph import Ontology

COST_BAND_TOLERANCE = 1


def _span(source: str, path: str, excerpt: str) -> EvidenceSpan:
    return EvidenceSpan(source=source, path=path, excerpt=str(excerpt))


def alignment_checks(
    ont: Ontology, dna: ConceptDNA, program: DesignProgram, scene: SceneGraph | None
) -> tuple[list[CriticFinding], list[str]]:
    findings: list[CriticFinding] = []
    ran = ["ALIGN_CAPACITY_SHORT", "ALIGN_AREA_OVERFLOW", "ALIGN_ZONE_MISSING", "ALIGN_SCHEDULE_EXCEEDED"]
    if scene:
        if scene.derived.total_capacity < program.capacity.guests:
            findings.append(CriticFinding(
                code=codes.ALIGN_CAPACITY_SHORT, severity=Severity.BLOCKER,
                statement=f"Scene capacity {scene.derived.total_capacity} is short of "
                          f"{program.capacity.guests} required.",
                evidence=[_span("SCENE_GRAPH", "derived.total_capacity", scene.derived.total_capacity)],
                facet_ref="scale_strategy", repair_hint="increase scale_strategy rank",
            ))
        if scene.derived.total_zone_area_m2 > program.site.usable_area_m2:
            findings.append(CriticFinding(
                code=codes.ALIGN_AREA_OVERFLOW, severity=Severity.BLOCKER,
                statement=f"Zones total {scene.derived.total_zone_area_m2:.0f} m² on a "
                          f"{program.site.usable_area_m2:.0f} m² site.",
                evidence=[_span("SCENE_GRAPH", "derived.total_zone_area_m2",
                                scene.derived.total_zone_area_m2)],
                facet_ref="scale_strategy", repair_hint="reduce scale_strategy rank",
            ))
        present = {n.role for n in scene.by_type("zone")}
        for z in program.required_zones:
            if z.zone not in present:
                findings.append(CriticFinding(
                    code=codes.ALIGN_ZONE_MISSING, severity=Severity.MAJOR,
                    statement=f"Required zone '{z.zone}' is absent from the scene graph.",
                    evidence=[_span("PROGRAM", "required_zones", z.zone)],
                ))
        if scene.derived.build_days * 24 > program.schedule.load_in_hours * 1.5:
            findings.append(CriticFinding(
                code=codes.ALIGN_SCHEDULE_EXCEEDED, severity=Severity.MAJOR,
                statement=f"Estimated {scene.derived.build_days:.1f} build days exceeds the "
                          f"{program.schedule.load_in_hours:.0f} h load-in window.",
                evidence=[_span("SCENE_GRAPH", "derived.build_days", scene.derived.build_days)],
                facet_ref="tectonic_logic", repair_hint="attenuate or substitute material",
            ))
    return findings, ran


def coherence_checks(
    ont: Ontology, dna: ConceptDNA, program: DesignProgram, fidelity_failures: list[str]
) -> tuple[list[CriticFinding], list[str]]:
    findings: list[CriticFinding] = []
    ran = ["COH_EXCLUDES_VIOLATION", "COH_REQUIRES_UNMET", "COH_TENSION_UNRECONCILED", "COH_FIDELITY"]
    refs = dna.genotype.all_refs()
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            if b in ont.excludes(a):
                findings.append(CriticFinding(
                    code=codes.COH_EXCLUDES_VIOLATION, severity=Severity.BLOCKER,
                    statement=f"{ont.label(a)} and {ont.label(b)} cannot coexist.",
                    evidence=[_span("GENOTYPE", "excludes", f"{a} × {b}")],
                    facet_ref=b.split(":")[0], repair_hint="replace the lower-weighted member",
                ))
    have = set(dna.genotype.technology)
    for r in refs:
        for need in ont.requires(r):
            if need not in have:
                findings.append(CriticFinding(
                    code=codes.COH_REQUIRES_UNMET, severity=Severity.MAJOR,
                    statement=f"{ont.label(r)} requires {need.split(':')[-1].replace('_', ' ')}, "
                              f"which is absent.",
                    evidence=[_span("GENOTYPE", "technology", need)],
                    repair_hint="deterministic closure: add the required value",
                ))
    tensions = [(a, b) for a, b, _ in _active_tensions(ont, refs)]
    if tensions and not dna.phenotype.reconciliation_thesis:
        a, b = tensions[0]
        findings.append(CriticFinding(
            code=codes.COH_TENSION_UNRECONCILED, severity=Severity.MAJOR,
            statement=f"{ont.label(a)} and {ont.label(b)} are in tension with no reconciliation.",
            evidence=[_span("GENOTYPE", "tensions_with", f"{a} × {b}")],
            repair_hint="re-express with a reconciliation thesis",
        ))
    for f in fidelity_failures:
        findings.append(CriticFinding(
            code=codes.COH_SOURCE_NAMED if f.startswith("F5") else codes.COH_FIDELITY,
            severity=Severity.MAJOR if f.startswith(("F1", "F5")) else Severity.MINOR,
            statement=f, evidence=[_span("PHENOTYPE", "fidelity", f[:120])],
            repair_hint="re-express only; the genotype is unchanged",
        ))
    return findings, ran


def _active_tensions(ont: Ontology, refs: list[str]) -> list[tuple[str, str, float]]:
    present, seen, out = set(refs), set(), []
    for r in present:
        for other, w in ont.tensions(r):
            if other in present:
                key = frozenset({r, other})
                if key not in seen:
                    seen.add(key)
                    out.append((r, other, w))
    return out


def feasibility_checks(
    ont: Ontology, dna: ConceptDNA, program: DesignProgram, scene: SceneGraph | None
) -> tuple[list[CriticFinding], list[str]]:
    findings: list[CriticFinding] = []
    ran = ["FEAS_SPAN_EXCEEDED", "FEAS_COST_BAND", "FEAS_MATERIAL_STRUCTURE_INCOMPATIBLE",
           "FEAS_CLIMATE_INCOMPATIBLE"]
    g = dna.genotype
    primary = g.primary_material()
    p_node = ont.node(primary.material)
    s_node = ont.node(g.structural_logic.value)

    required_span = scene.derived.max_span_m if scene else 0.0
    material_span = p_node.span or 0.0
    struct_span = s_node.span or 0.0
    if required_span > 0 and material_span > 0 and required_span > max(material_span, struct_span):
        findings.append(CriticFinding(
            code=codes.FEAS_SPAN_EXCEEDED, severity=Severity.BLOCKER,
            statement=f"{p_node.label} spans at most {material_span} m but the scene requires "
                      f"{required_span:.1f} m.",
            evidence=[_span("SCENE_GRAPH", "derived.max_span_m", round(required_span, 1))],
            facet_ref="material_palette", repair_hint="substitute the primary material",
        ))
    if material_span and struct_span and material_span < struct_span * 0.25:
        findings.append(CriticFinding(
            code=codes.FEAS_MATERIAL_STRUCTURE_INCOMPATIBLE, severity=Severity.MAJOR,
            statement=f"{p_node.label} is a poor primary for a {s_node.label.lower()} system.",
            evidence=[_span("GENOTYPE", "structural_logic", f"{primary.material} + {g.structural_logic.value}")],
            facet_ref="material_palette", repair_hint="substitute the primary material",
        ))
    cost = max(ont.node(r).cost for r in g.all_refs() if r in ont.nodes)
    if cost > program.budget.band + COST_BAND_TOLERANCE:
        findings.append(CriticFinding(
            code=codes.FEAS_COST_BAND, severity=Severity.BLOCKER,
            statement=f"Concept peaks at cost band {cost} against a budget band {program.budget.band}.",
            evidence=[_span("GENOTYPE", "cost_band", cost)],
            facet_ref="material_palette", repair_hint="attenuate, then substitute material",
        ))
    climate = program.site.climate.label
    for r in g.all_refs():
        node = ont.nodes.get(r)
        if node and climate in node.climate_bad:
            findings.append(CriticFinding(
                code=codes.FEAS_CLIMATE_INCOMPATIBLE, severity=Severity.MAJOR,
                statement=f"{node.label} is unsuitable in a {climate.replace('_', ' ')} climate.",
                evidence=[_span("GENOTYPE", r, climate)],
                facet_ref=r.split(":")[0], repair_hint="substitute the material",
            ))
    return findings, ran


def semantic_checks(
    ont: Ontology, dna: ConceptDNA, program: DesignProgram, scene: SceneGraph | None
) -> tuple[list[CriticFinding], list[str]]:
    """Does this concept solve the event that was asked for, and only that event?

    Entirely deterministic. The same scope rule and the same leak detector used by
    Design Intelligence decide it, so the critic cannot disagree with the reading.
    """
    from app.semantics.knowledge import load_knowledge
    from app.semantics.leakage import find_leaks_in
    from app.semantics.priors import value_out_of_scope

    ran = [codes.SEM_OUT_OF_SCOPE_VALUE, codes.SEM_FORBIDDEN_ELEMENT,
           codes.SEM_REQUIRED_ZONE_MISSING, codes.SEM_FOCUS_MISSING]
    sem = program.semantic
    findings: list[CriticFinding] = []
    if sem is None:
        return findings, []
    k = load_knowledge()
    label = sem.profile.identity.event_type_label

    for ref in dna.genotype.all_refs():
        node = ont.nodes.get(ref)
        why = value_out_of_scope(node, sem) if node else None
        if why:
            findings.append(CriticFinding(
                code=codes.SEM_OUT_OF_SCOPE_VALUE, severity=Severity.BLOCKER,
                statement=f"{node.label} does not belong to a {label}: {why}.",
                evidence=[_span("GENOTYPE", ref.split(":")[0], ref)],
                facet_ref=ref.split(":")[0]))

    ph = dna.phenotype
    fields = {
        "phenotype.title": ph.title, "phenotype.one_line": ph.one_line,
        "phenotype.design_thesis": ph.design_thesis,
        "phenotype.spatial_explanation": ph.spatial_explanation,
        "phenotype.material_explanation": ph.material_explanation,
        "phenotype.experience_narrative": ph.experience_narrative,
        "phenotype.atmosphere": ph.visual_direction.atmosphere,
    }
    if scene is not None:
        for n in scene.nodes:
            if n.type in ("zone", "focal") and n.role:
                fields[f"scene.{n.id}"] = n.role.replace("_", " ")
    for leak in find_leaks_in(k, sem.profile, fields):
        findings.append(CriticFinding(
            code=codes.SEM_FORBIDDEN_ELEMENT, severity=Severity.BLOCKER,
            statement=f"A {leak.label.lower()} appears in a {label}: {leak.rule}.",
            evidence=[_span("SCENE_GRAPH" if leak.where.startswith("scene") else "PHENOTYPE",
                            leak.where, leak.phrase)]))

    if scene is not None and scene.status != "FAILED":
        present = {n.role for n in scene.by_type("zone")}
        for z in sem.programme:
            if z.priority == "required" and z.key not in present:
                findings.append(CriticFinding(
                    code=codes.SEM_REQUIRED_ZONE_MISSING, severity=Severity.MAJOR,
                    statement=f"The {label} needs a {z.label.lower()} ({z.rationale}); "
                              f"the scene has none.",
                    evidence=[_span("PROGRAM", "semantic.programme", z.key)]))
        focus = sem.intent.primary_zone_key
        if focus and focus not in present:
            findings.append(CriticFinding(
                code=codes.SEM_FOCUS_MISSING, severity=Severity.MAJOR,
                statement=f"The concept has no {sem.intent.primary_focus.lower()}, "
                          f"which is what a {label} is organised around.",
                evidence=[_span("PROGRAM", "semantic.intent.primary_zone_key", focus)]))
    return findings, ran


def cultural_checks(
    ont: Ontology, dna: ConceptDNA, program: DesignProgram
) -> tuple[list[CriticFinding], list[str]]:
    findings: list[CriticFinding] = []
    ran = ["CULT_SACRED_MISSING", "CULT_ABSTRACTION_FLOOR", "CULT_RESTRICTED_VALUE"]
    for cref in dna.genotype.cultural_lineage:
        node = ont.nodes.get(cref.ref)
        if node and cref.abstraction < node.min_abstraction:
            findings.append(CriticFinding(
                code=codes.CULT_ABSTRACTION_FLOOR, severity=Severity.MAJOR,
                statement=f"{node.label} requires abstraction >= {node.min_abstraction}; "
                          f"this concept uses {cref.abstraction}.",
                evidence=[_span("GENOTYPE", "cultural_lineage", cref.ref)],
                repair_hint="apply the abstract operator",
            ))
        if node and node.sensitivity == "restricted":
            findings.append(CriticFinding(
                code=codes.CULT_RESTRICTED_VALUE, severity=Severity.BLOCKER,
                statement=f"{node.label} is a restricted reference for this brief.",
                evidence=[_span("GENOTYPE", "cultural_lineage", cref.ref)],
            ))
    # sacred programme elements must survive into the scene graph, checked in scene checks
    return findings, ran
