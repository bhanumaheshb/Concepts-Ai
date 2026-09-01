"""The anti-brief.

Naming the cliché is not the same as banning it. The anti-brief makes the mode
*visible* to the allocator so exactly one concept can occupy it deliberately and
the rest can avoid it knowingly.

Never fails: with no provider configured it falls back to the curated seeds in
`cliches.yaml`, which is also the production fallback path (spec R-ANTI-01).
"""
from __future__ import annotations

import difflib
import re

from app.core.ids import deterministic_id
from app.core.seeded import SeededRandom
from app.domain.antibrief import (
    AntiBrief, AntiBriefProposal, ClicheCluster, QuestionedAssumption,
)
from app.domain.brief import DesignProgram
from app.domain.genotype import PartialGenotype
from app.domain.space import CreativeSearchSpace
from app.ontology.graph import Ontology

MATCH_THRESHOLD = 0.80
# Weight by how much the evidence for a cliché is worth when two clusters merge.
# ARCHIVE is heaviest (we OBSERVED the engine produce it), REFERENCE is next (the
# literal reading of a real reference is a real cliché), LLM is a guess.
# REFERENCE was missing here and raised KeyError the first time a reference-derived
# cluster overlapped a curated one by >= MATCH_THRESHOLD.
SOURCE_WEIGHT = {"CURATED": 1.0, "LLM": 0.7, "ARCHIVE": 1.2, "REFERENCE": 1.1}

SKELETON_FACETS = {
    "architectural_language": "architectural_language",
    "geometry_system": "geometry_system",
    "structural_logic": "structural_logic",
    "tectonic_logic": "tectonic_logic",
    "occupation_staging": "occupation_staging",
    "lighting_philosophy": "lighting_philosophy",
    "site_relationship": "site_relationship",
    "thesis_archetype": "thesis_archetype",
    "emotional_register": "emotional_register",
    "scale_strategy": "scale_strategy",
}


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def map_to_ontology(ont: Ontology, text: str) -> str | None:
    """Deterministic, no embeddings. Unmapped text is DISCARDED, never invented —
    which is why the model returns free text and code owns the ontology refs."""
    n = _normalise(text)
    if not n:
        return None
    best, best_score = None, 0.0
    for node in ont.nodes.values():
        if node.abstract:
            continue
        for candidate in (node.label, node.value.replace("_", " ")):
            score = difflib.SequenceMatcher(None, n, _normalise(candidate)).ratio()
            if score > best_score:
                best, best_score = node.id, score
    return best if best_score >= MATCH_THRESHOLD else None


def _curated(ont: Ontology, program: DesignProgram) -> list[ClicheCluster]:
    seeds = ont.cliches.get(program.typology.value) or ont.cliches.get("GENERIC_SPATIAL", [])
    return [
        ClicheCluster(
            cluster_id=deterministic_id("cl", program.typology.value, s.label),
            label=s.label, facet_values=list(s.facet_values), prevalence=s.prevalence,
            evidence="CURATED", surface_tokens=list(s.surface_tokens),
        )
        for s in seeds
    ]


def _from_proposal(ont: Ontology, program: DesignProgram, proposal: AntiBriefProposal) -> list[ClicheCluster]:
    out: list[ClicheCluster] = []
    for c in proposal.cliches:
        refs = [r for r in (map_to_ontology(ont, e) for e in c.elements) if r]
        refs = list(dict.fromkeys(refs))
        if len(refs) < 2:
            continue           # a single common material is not a cliché
        out.append(ClicheCluster(
            cluster_id=deterministic_id("cl", program.typology.value, c.label, "llm"),
            label=c.label, facet_values=refs, prevalence=0.6, evidence="LLM",
            surface_tokens=list(c.surface_tokens),
        ))
    return out


def _merge(clusters: list[ClicheCluster]) -> list[ClicheCluster]:
    merged: list[ClicheCluster] = []
    for c in sorted(clusters, key=lambda x: -x.prevalence):
        target = None
        for m in merged:
            a, b = set(c.facet_values), set(m.facet_values)
            if a & b and len(a & b) / len(a | b) >= 0.6:
                target = m
                break
        if target is None:
            merged.append(c)
            continue
        i = merged.index(target)
        wa, wb = SOURCE_WEIGHT[c.evidence], SOURCE_WEIGHT[target.evidence]
        merged[i] = target.model_copy(update={
            "facet_values": sorted(set(target.facet_values) | set(c.facet_values)),
            "surface_tokens": sorted(set(target.surface_tokens) | set(c.surface_tokens)),
            "prevalence": round(min(1.0, (target.prevalence * wb + c.prevalence * wa) / (wa + wb)), 3),
        })
    return merged


def _canonical_seed(
    ont: Ontology, space: CreativeSearchSpace, clusters: list[ClicheCluster]
) -> tuple[PartialGenotype, str]:
    """A low-budget brief may have NO legal cliché — every gilded value is pruned.
    Fall back to the modal legal genotype, which is the conventional answer within
    what this brief actually permits."""
    for c in sorted(clusters, key=lambda x: -x.prevalence):
        fields: dict[str, str] = {}
        for ref in c.facet_values:
            facet = ref.split(":", 1)[0]
            if facet == "material":
                if space.is_legal("material_palette", ref):
                    fields.setdefault("material_primary", ref)
                continue
            if facet in SKELETON_FACETS and space.is_legal(facet, ref):
                fields.setdefault(facet, ref)
        if len(fields) >= 2:
            return PartialGenotype(**fields), f"cluster:{c.label}"
    # modal legal fallback
    fields = {}
    for facet in ("architectural_language", "geometry_system", "occupation_staging"):
        domain = space.domain(facet)
        top = max(domain.legal, key=lambda v: (v.weight, v.value))
        fields[facet] = top.value
    return PartialGenotype(**fields), "modal_legal_fallback"


def build_antibrief(
    ont: Ontology,
    program: DesignProgram,
    space: CreativeSearchSpace,
    proposal: AntiBriefProposal | None = None,
    seed: int = 0,
    extra_clusters: list[ClicheCluster] | None = None,
) -> AntiBrief:
    """`extra_clusters` carries a reference's LITERAL READING. Because it arrives before
    the canonical seed is computed and carries a high prevalence, the canonical concept
    becomes the deliberate literal interpretation and the existing quota keeps the other
    nine away from it — no new divergence logic (spec §0)."""
    clusters = _merge(_curated(ont, program)
                      + (_from_proposal(ont, program, proposal) if proposal else [])
                      + list(extra_clusters or []))
    sacred = program.sacred_refs()

    assumptions: list[QuestionedAssumption] = []
    for i, a in enumerate(proposal.questioned_assumptions if proposal else []):
        facet = a.facet_hint if a.facet_hint in SKELETON_FACETS else None
        blocked = next(
            (c.constraint_id for c in program.invariants
             if c.sacred and any(w in a.statement.lower() for w in c.statement.lower().split()[:4])),
            None,
        )
        assumptions.append(QuestionedAssumption(
            assumption_id=f"qa_{i}", statement=a.statement, inverts_facet=facet, blocked_by=blocked,
        ))
    if not assumptions:
        assumptions = [
            QuestionedAssumption(assumption_id="qa_0", inverts_facet="occupation_staging",
                                 statement="The focus must be raised above the audience."),
            QuestionedAssumption(assumption_id="qa_1", inverts_facet="site_relationship",
                                 statement="The structure must sit on the ground."),
            QuestionedAssumption(assumption_id="qa_2", inverts_facet="thesis_archetype",
                                 statement="The design must be an object rather than a void."),
        ]
    if sacred:
        assumptions.append(QuestionedAssumption(
            assumption_id="qa_sacred", statement="The ritual elements could be omitted.",
            inverts_facet=None,
            blocked_by=next((c.constraint_id for c in program.invariants if c.sacred), "c_ritual"),
        ))

    seed_geno, source = _canonical_seed(ont, space, clusters)
    return AntiBrief(
        antibrief_id=deterministic_id("ab", program.program_id, str(seed)),
        program_id=program.program_id,
        cliche_clusters=clusters,
        questioned_assumptions=assumptions,
        canonical_seed=seed_geno,
        canonical_seed_source=source,
        generated_by="mock" if proposal else None,
    )
