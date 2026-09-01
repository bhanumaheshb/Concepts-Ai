"""Critic runner.

Deterministic checks run first and short-circuit the LLM half on a blocker
(spec R-CRIT-01). The model emits FINDINGS WITH EVIDENCE; the score is derived in
code from the finding set, so it is comparable across releases and cannot drift
with prompt wording. Findings that arrive without evidence are discarded (R-CRIT-02).
"""
from __future__ import annotations

import time

from app.core.versions import CRITIC_VERSION
from app.creative.context import CriticContext
from app.creative.schemas import CriticLLMOutput
from app.critics import codes
from app.critics.deterministic import (
    alignment_checks, coherence_checks, cultural_checks, feasibility_checks,
)
from app.domain.brief import DesignProgram
from app.domain.common import CriticName, ModelTier, Severity
from app.domain.concept import ConceptDNA
from app.domain.evaluation import (
    CriticFinding, CriticResult, EvaluationResult, NoveltyScore,
)
from app.domain.providers.protocols import LLMProvider, PromptBlock, PromptEnvelope
from app.domain.scene import SceneGraph
from app.ontology.graph import Ontology

SEVERITY_WEIGHT = {Severity.BLOCKER: 1.00, Severity.MAJOR: 0.25, Severity.MINOR: 0.08}
GATES = {
    CriticName.ALIGNMENT: 0.70,
    CriticName.COHERENCE: 0.70,
    CriticName.FEASIBILITY: 0.55,
    CriticName.CULTURAL: 0.99,   # strictest: no finding at MAJOR or above
}
Q_WEIGHTS = {CriticName.ALIGNMENT: 0.35, CriticName.COHERENCE: 0.35, CriticName.FEASIBILITY: 0.30}


def derive_score(findings: list[CriticFinding]) -> float:
    """A blocker is structurally a zero. The model never supplies this number."""
    if any(f.severity == Severity.BLOCKER for f in findings):
        return 0.0
    return max(0.0, 1.0 - sum(SEVERITY_WEIGHT[f.severity] for f in findings))


def _gate(critic: CriticName, score: float, findings: list[CriticFinding]) -> bool:
    if any(f.severity == Severity.BLOCKER for f in findings):
        return False
    if critic == CriticName.CULTURAL:
        return not any(f.severity in (Severity.BLOCKER, Severity.MAJOR) for f in findings)
    return score >= GATES[critic]


def _llm_findings(
    llm: LLMProvider, dna: ConceptDNA, program: DesignProgram, critic: CriticName, seed: int
) -> tuple[list[CriticFinding], int]:
    envelope = PromptEnvelope(
        prompt_id=f"critic.{critic.value.lower()}", version="1.0.0",
        blocks=[
            PromptBlock(role="system", cacheable=True, text=(
                "Quote the span you are judging BEFORE you judge it. Every finding must "
                "carry at least one evidence span. Do not emit a score.")),
            PromptBlock(role="user", cacheable=True, text=f"PROGRAMME\n{program.summary}"),
            PromptBlock(role="user", cacheable=False,
                        text=f"CONCEPT\n{dna.phenotype.title}\n{dna.phenotype.design_thesis}"),
        ],
        schema_ref="CriticLLMOutput", tier=ModelTier.CRITIQUE, max_output_tokens=2048,
    )
    resp = llm.complete_structured(
        envelope=envelope, schema=CriticLLMOutput, seed=seed,
        context=CriticContext(concept=dna, program=program, critic=critic.value),
    )
    out: CriticLLMOutput = resp.value
    kept = [
        CriticFinding(code=f.code, severity=f.severity, statement=f.statement,
                      evidence=f.evidence, facet_ref=f.facet_ref, repair_hint=f.repair_hint)
        for f in out.findings if f.evidence      # no evidence, no finding
    ]
    return kept, 1


def run_critic(
    llm: LLMProvider, ont: Ontology, dna: ConceptDNA, program: DesignProgram,
    critic: CriticName, scene: SceneGraph | None, fidelity_failures: list[str], seed: int,
    use_llm: bool = True,
) -> tuple[CriticResult, int]:
    started = time.perf_counter()
    if critic == CriticName.ALIGNMENT:
        findings, ran = alignment_checks(ont, dna, program, scene)
    elif critic == CriticName.COHERENCE:
        findings, ran = coherence_checks(ont, dna, program, fidelity_failures)
    elif critic == CriticName.FEASIBILITY:
        findings, ran = feasibility_checks(ont, dna, program, scene)
    else:
        findings, ran = cultural_checks(ont, dna, program)

    calls = 0
    blocked = any(f.severity == Severity.BLOCKER for f in findings)
    if use_llm and not blocked:          # R-CRIT-01: skip the model when already blocked
        extra, calls = _llm_findings(llm, dna, program, critic, seed)
        findings = findings + extra

    score = derive_score(findings)
    result = CriticResult(
        critic=critic, score=round(score, 4), passed=_gate(critic, score, findings),
        findings=findings,
        repair_instruction=next((f.repair_hint for f in findings if f.repair_hint), "") or "",
        deterministic_checks_run=ran, llm_used=calls > 0,
        duration_ms=int((time.perf_counter() - started) * 1000), critic_version=CRITIC_VERSION,
    )
    return result, calls


def evaluate(
    llm: LLMProvider, ont: Ontology, dna: ConceptDNA, program: DesignProgram,
    scene: SceneGraph | None, fidelity_failures: list[str], seed: int,
    novelty: float = 1.0, only: set[CriticName] | None = None,
    previous: EvaluationResult | None = None, use_llm: bool = True,
    originality: CriticResult | None = None,
) -> tuple[EvaluationResult, int]:
    """`only` re-runs a subset after a repair; everything else is carried forward."""
    results: dict[CriticName, CriticResult] = {}
    calls = 0
    for critic in (CriticName.ALIGNMENT, CriticName.COHERENCE,
                   CriticName.FEASIBILITY, CriticName.CULTURAL):
        if only is not None and critic not in only and previous is not None:
            results[critic] = getattr(previous, critic.value.lower())
            continue
        res, c = run_critic(llm, ont, dna, program, critic, scene, fidelity_failures, seed, use_llm)
        results[critic] = res
        calls += c

    if originality is None and previous is not None:
        originality = previous.originality
    gate = all(r.passed for r in results.values()) and (originality is None or originality.passed)
    q = 1.0
    for critic, w in Q_WEIGHTS.items():
        q *= max(1e-6, results[critic].score) ** w      # geometric: no compensation
    return EvaluationResult(
        concept_id=dna.concept_id,
        alignment=results[CriticName.ALIGNMENT], coherence=results[CriticName.COHERENCE],
        feasibility=results[CriticName.FEASIBILITY], cultural=results[CriticName.CULTURAL],
        originality=originality,
        novelty=NoveltyScore(vs_platform=round(min(1.0, novelty), 4), k=5),
        gate_passed=gate, quality_q=round(min(1.0, q), 4),
    ), calls
