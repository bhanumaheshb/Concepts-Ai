"""Phenotype synthesis.

The genotype is solved and validated *before* the model is called; synthesis only
expresses it. A deterministic fidelity check then decides whether the prose actually
expresses the vector it was given — without which the genotype/phenotype split is
decorative.
"""
from __future__ import annotations

import re

from app.creative.context import PhenotypeContext
from app.domain.brief import DesignProgram
from app.domain.common import ModelTier
from app.domain.genotype import ConceptGenotype
from app.domain.phenotype import ConceptPhenotype
from app.domain.providers.protocols import (
    LLMProvider, PromptBlock, PromptEnvelope,
)
from app.ontology.graph import Ontology

PROMPT_VERSION = "1.0.0"

HOUSE_RULES = """You are expressing a design decision that has ALREADY been made.
Do not propose alternatives, do not hedge, do not offer variations.

Rules:
1. Every entry in rationale_chain MUST cite a constraint_id from the programme below.
   If you cannot justify a move against a stated constraint, remove the move.
2. You may not introduce architectural, material or geometric choices beyond those in
   the genotype. The genotype is complete.
3. Do not name the source domain of any principle you are given. Express the
   principle; the source is not part of the concept.
4. what_it_is_not must name this concept's anti-attributes and say they are absent.
5. signature_read is the single word a person would use for how this space reads."""


def build_envelope(
    ont: Ontology, program: DesignProgram, genotype: ConceptGenotype,
    principle_statements: list[str], forbidden_tokens: list[str],
) -> PromptEnvelope:
    """Three blocks in fixed order so the first two cache across all k concepts.

    Block B is sorted by ontology ref — if the iteration order varies the prefix
    changes and the cache never hits, which is a silent, expensive bug.
    """
    block_a = PromptBlock(role="system", text=HOUSE_RULES, cacheable=True)
    briefings = "\n".join(
        f"- {ref}: {ont.node(ref).label} — {ont.node(ref).desc or ont.node(ref).label}"
        for ref in sorted(set(genotype.all_refs())) if ref in ont.nodes
    )
    block_b = PromptBlock(
        role="user",
        text=f"PROGRAMME\n{program.summary}\n\nCONSTRAINTS\n"
             + "\n".join(f"- {c.constraint_id}: {c.statement}" for c in program.invariants)
             + f"\n\nONTOLOGY BRIEFINGS\n{briefings}",
        cacheable=True,
    )
    rows = "\n".join(f"- {k}: {v}" for k, v in genotype.as_display_rows())
    extra = ""
    if principle_statements:
        extra += "\n\nThis concept must satisfy, in its own material and cultural terms:\n"
        extra += "\n".join(f"  · {s}" for s in principle_statements)
    if forbidden_tokens:
        extra += "\nIt must not use any of these words: " + ", ".join(forbidden_tokens) + "."
    block_c = PromptBlock(role="user", text=f"GENOTYPE\n{rows}{extra}", cacheable=False)
    return PromptEnvelope(
        prompt_id="phenotype.synthesis", version=PROMPT_VERSION,
        blocks=[block_a, block_b, block_c], schema_ref="ConceptPhenotype",
        tier=ModelTier.SYNTHESIS, max_output_tokens=4096, timeout_s=90.0,
    )


# ---------------- fidelity checks (deterministic) ----------------

def _tokens_of(ont: Ontology, refs: list[str]) -> list[str]:
    out: list[str] = []
    for r in refs:
        node = ont.nodes.get(r)
        if node:
            out.append(node.label.lower())
            out.extend(node.neg)
        out.append(r.split(":", 1)[-1].replace("_", " "))
    return [t for t in {t.strip().lower() for t in out} if len(t) > 3]


def _contains_token(text: str, token: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", text, re.I) is not None


def fidelity_check(
    ont: Ontology, program: DesignProgram, genotype: ConceptGenotype,
    phenotype: ConceptPhenotype, forbidden_tokens: list[str], sibling_titles: list[str],
) -> list[str]:
    """Seven checks. Any failure triggers one targeted retry quoting only what failed."""
    failures: list[str] = []
    head = " ".join([phenotype.title, phenotype.one_line, phenotype.design_thesis])

    valid_ids = program.constraint_ids()
    for i, link in enumerate(phenotype.rationale_chain):
        ref = link.evidence_ref
        ok = ref in valid_ids or (ref.startswith("program.") and len(ref) > 8)
        if not ok:
            failures.append(f"F1 rationale_chain[{i}].evidence_ref '{ref}' does not resolve. "
                            f"Valid ids: {', '.join(sorted(valid_ids))}")

    for token in _tokens_of(ont, genotype.anti_attributes):
        if _contains_token(head, token):
            failures.append(f"F2 anti-attribute token '{token}' appears in the concept's headline text")

    has_tension = bool([t for t in ont.tensions(genotype.architectural_language.value)
                        if t[0] in set(genotype.all_refs())])
    if has_tension and not phenotype.reconciliation_thesis:
        failures.append("F3 genotype contains a tensions_with pair but no reconciliation_thesis")
    if not has_tension and phenotype.reconciliation_thesis:
        failures.append("F3 reconciliation_thesis present without a tension to reconcile")

    for cref in genotype.cultural_lineage:
        if cref.abstraction < 0.6 and not phenotype.precedent_notes:
            failures.append(f"F4 cultural reference {cref.ref} at abstraction "
                            f"{cref.abstraction} requires a precedent note")

    whole = " ".join([head, phenotype.spatial_explanation, phenotype.material_explanation,
                      phenotype.experience_narrative])
    for token in forbidden_tokens:
        if _contains_token(whole, token):
            failures.append(f"F5 forbidden source token '{token}' appears — express the principle, "
                            f"do not name its source")

    t = phenotype.title.strip().lower()
    for other in sibling_titles:
        if t == other.strip().lower():
            failures.append(f"F6 title '{phenotype.title}' collides with an existing concept")

    moves = [l.move.strip().lower() for l in phenotype.rationale_chain]
    if len(phenotype.rationale_chain) < 3:
        failures.append("F7 rationale_chain must contain at least 3 links")
    if len(set(moves)) != len(moves):
        failures.append("F7 rationale_chain contains duplicate moves")
    if len(phenotype.design_thesis.split()) < 60:
        failures.append("F7 design_thesis is too short")
    return failures


def synthesise_phenotype(
    llm: LLMProvider, ont: Ontology, program: DesignProgram, genotype: ConceptGenotype,
    *, role, seed: int, principle_statements: list[str] | None = None,
    forbidden_tokens: list[str] | None = None, sibling_titles: list[str] | None = None,
    preserve_title: str | None = None, preserve_signature: str | None = None,
    fix_notes: list[str] | None = None,
) -> tuple[ConceptPhenotype, list[str], int]:
    """Returns (phenotype, remaining_fidelity_failures, llm_calls)."""
    principle_statements = principle_statements or []
    forbidden_tokens = forbidden_tokens or []
    sibling_titles = sibling_titles or []
    envelope = build_envelope(ont, program, genotype, principle_statements, forbidden_tokens)
    calls = 0
    failures: list[str] = []
    phenotype: ConceptPhenotype | None = None

    for attempt in range(2):
        ctx = PhenotypeContext(
            genotype=genotype, program=program, role=role,
            principle_statements=principle_statements, forbidden_tokens=forbidden_tokens,
            sibling_titles=sibling_titles, preserve_title=preserve_title,
            preserve_signature=preserve_signature,
            fix_notes=(fix_notes or []) + failures,
        )
        env = envelope
        if failures:
            # targeted retry: send only what failed, not the whole instruction again
            env = envelope.model_copy(update={"blocks": envelope.blocks + [PromptBlock(
                role="user",
                text="These checks failed on your previous response. Return the corrected "
                     "object and change nothing else.\n" + "\n".join(failures),
                cacheable=False)]})
        resp = llm.complete_structured(
            envelope=env, schema=ConceptPhenotype, seed=seed + attempt, context=ctx
        )
        calls += 1
        phenotype = resp.value
        failures = fidelity_check(ont, program, genotype, phenotype, forbidden_tokens, sibling_titles)
        if not failures:
            break
    assert phenotype is not None
    return phenotype, failures, calls
