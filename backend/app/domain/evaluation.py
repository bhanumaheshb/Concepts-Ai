from __future__ import annotations

from app.domain.common import CriticName, FacetId, Frozen, Score, Severity


class EvidenceSpan(Frozen):
    source: str    # PHENOTYPE | GENOTYPE | SCENE_GRAPH | PROGRAM
    path: str
    excerpt: str


class CriticFinding(Frozen):
    code: str
    severity: Severity
    statement: str
    evidence: list[EvidenceSpan] = []
    facet_ref: FacetId | None = None
    repair_hint: str | None = None


class CriticResult(Frozen):
    critic: CriticName
    score: Score
    passed: bool
    findings: list[CriticFinding] = []
    repair_instruction: str = ""
    deterministic_checks_run: list[str] = []
    llm_used: bool = False
    duration_ms: int = 0
    critic_version: str = "1.0.0"


class NoveltyScore(Frozen):
    vs_platform: Score = 0.5
    vs_corpus: Score | None = None
    vs_client: Score | None = None
    k: int = 0


class EvaluationResult(Frozen):
    concept_id: str
    alignment: CriticResult
    coherence: CriticResult
    feasibility: CriticResult
    cultural: CriticResult
    originality: CriticResult | None = None      # present only in reference mode
    novelty: NoveltyScore = NoveltyScore()
    gate_passed: bool
    quality_q: Score

    def results(self) -> list[CriticResult]:
        base = [self.alignment, self.coherence, self.feasibility, self.cultural]
        return base + ([self.originality] if self.originality else [])

    def blockers(self) -> list[CriticFinding]:
        return [f for r in self.results() for f in r.findings if f.severity == Severity.BLOCKER]

    def all_findings(self) -> list[CriticFinding]:
        return [f for r in self.results() for f in r.findings]
