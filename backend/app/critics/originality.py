"""The fifth critic — ORIGINALITY.

Runs only when a reference is present. Its deterministic half owns the gates; an LLM
may add a finding but never contributes to T (R-REF-09).

Canonical is exempt from the T gate — it is the deliberate literal interpretation and
its low transformation is the point. It is NOT exempt from surface leakage (R-REF-10).
"""
from __future__ import annotations

import time

from app.core.versions import CRITIC_VERSION
from app.domain.common import CriticName, NicheRole, Severity
from app.domain.evaluation import CriticFinding, CriticResult, EvidenceSpan
from app.domain.reference import ReferenceContext

REF_SURFACE_LEAK = "REF_SURFACE_LEAK"
REF_UNDER_TRANSFORMED = "REF_UNDER_TRANSFORMED"
REF_LITERAL_OCCUPANCY = "REF_LITERAL_OCCUPANCY"
REF_INFLUENCE_ABSENT = "REF_INFLUENCE_ABSENT"

T_GATE = 0.55
OCCUPANCY_CEILING = 0.60
I_FLOOR = 0.25


def run_originality(ctx: ReferenceContext, role: NicheRole) -> CriticResult:
    started = time.perf_counter()
    findings: list[CriticFinding] = []
    checks = [REF_SURFACE_LEAK, REF_LITERAL_OCCUPANCY, REF_UNDER_TRANSFORMED, REF_INFLUENCE_ABSENT]

    # 1 — surface leakage: zero tolerance, every role, no exemption
    if ctx.surface_leaks:
        findings.append(CriticFinding(
            code=REF_SURFACE_LEAK, severity=Severity.BLOCKER,
            statement=f"The concept names its source: {', '.join(ctx.surface_leaks)}.",
            evidence=[EvidenceSpan(source="PHENOTYPE", path="design_thesis",
                                   excerpt=", ".join(ctx.surface_leaks))],
            repair_hint="re-express only; the genotype is unchanged",
        ))

    literal = ctx.is_literal_slot or role is NicheRole.CANONICAL

    # 2 — literal occupancy, and 3 — transformation. Both exempt for the literal slot.
    if not literal:
        if ctx.channels.literal_occupancy > OCCUPANCY_CEILING:
            findings.append(CriticFinding(
                code=REF_LITERAL_OCCUPANCY, severity=Severity.MAJOR,
                statement=f"{ctx.channels.literal_occupancy:.0%} of this concept is the "
                          f"reference's own literal reading.",
                evidence=[EvidenceSpan(source="GENOTYPE", path="literal_occupancy",
                                       excerpt=f"{ctx.channels.literal_occupancy}")],
                facet_ref="architectural_language",
                repair_hint="apply the abstract operator, then transpose",
            ))
        if ctx.transformation < T_GATE:
            findings.append(CriticFinding(
                code=REF_UNDER_TRANSFORMED, severity=Severity.MAJOR,
                statement=f"Transformation {ctx.transformation:.2f} is below the {T_GATE} floor: "
                          f"the reference reached the concept but the concept did not escape it.",
                evidence=[EvidenceSpan(source="GENOTYPE", path="transformation",
                                       excerpt=f"O={ctx.channels.literal_occupancy} "
                                               f"D={ctx.channels.displacement} "
                                               f"X={ctx.channels.naive_overlap}")],
                repair_hint="reinterpret while preserving identity",
            ))

    # 4 — influence absent: a portfolio-level condition, reported per concept at MINOR
    if ctx.injected_principle_ids and ctx.influence_measured < I_FLOOR:
        findings.append(CriticFinding(
            code=REF_INFLUENCE_ABSENT, severity=Severity.MINOR,
            statement=f"The reference was injected but barely reached this concept "
                      f"(I={ctx.influence_measured:.2f}).",
            evidence=[EvidenceSpan(source="GENOTYPE", path="influence_measured",
                                   excerpt=f"{ctx.influence_measured}")],
        ))

    blockers = [f for f in findings if f.severity is Severity.BLOCKER]
    score = 0.0 if blockers else round(max(0.0, 1.0 - 0.25 * len(findings)), 4)
    return CriticResult(
        critic=CriticName.ORIGINALITY, score=score,
        passed=not blockers and not [f for f in findings if f.severity is Severity.MAJOR],
        findings=findings,
        repair_instruction=next((f.repair_hint for f in findings if f.repair_hint), "") or "",
        deterministic_checks_run=checks, llm_used=False,
        duration_ms=int((time.perf_counter() - started) * 1000), critic_version=CRITIC_VERSION,
    )
