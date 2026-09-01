"""The synthesis stage: one bounded call per concept, one repair if it fails.

No agent loop (§20/§22). For k=10 the budget is 10 synthesis calls plus only the
repairs validation actually demands, and every call is recorded so a bad concept can be
attributed to the engine, the model, or the compiler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.creative.synthesis_prompt import build_constraints
from app.creative.validator import ConceptLLMValidator
from app.domain.brief import DesignBrief, DesignProgram
from app.domain.concept import ConceptDNA
from app.domain.synthesis import (
    ConceptValidation, ConstraintEnvelope, StructuredArchitecturalConcept,
)
from app.ontology.graph import Ontology

MAX_REPAIRS = 1


@dataclass
class SynthesisTrace:
    """Everything needed to answer: engine, model, or compiler? (§25)"""
    concept_id: str
    provider: str = ""
    model: str = ""
    prompt: str = ""
    raw_output: dict | None = None
    attempts: int = 0
    repaired: bool = False
    repair_instruction: str = ""
    findings_before: list[str] = field(default_factory=list)
    findings_after: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str = ""


@dataclass
class SynthesisResult:
    concept: StructuredArchitecturalConcept | None
    validation: ConceptValidation
    constraints: ConstraintEnvelope
    trace: SynthesisTrace


class CreativeSynthesizer:
    """Provider-independent. Holds no knowledge of how any model is served."""

    def __init__(self, ont: Ontology, provider, max_repairs: int = MAX_REPAIRS) -> None:
        self.ont = ont
        self.provider = provider
        self.validator = ConceptLLMValidator(ont)
        self.max_repairs = max_repairs

    def synthesize(self, *, dna: ConceptDNA, brief: DesignBrief,
                   program: DesignProgram, forbidden_tokens: list[str] | None = None,
                   reference_statements: list[str] | None = None,
                   trend_statements: list[str] | None = None,
                   seed: int = 0) -> SynthesisResult:
        constraints = build_constraints(self.ont, program, brief, dna.genotype,
                                        forbidden_tokens)
        trace = SynthesisTrace(concept_id=dna.concept_id,
                               provider=getattr(self.provider, "name", "?"),
                               model=getattr(self.provider, "model", ""))

        concept, validation = None, ConceptValidation(passed=False)
        instruction = ""
        for attempt in range(1 + self.max_repairs):
            try:
                concept = self.provider.synthesize_concept(
                    concept_dna=dna, brief=brief, program=program,
                    constraints=constraints,
                    reference_context=reference_statements or [],
                    trend_context=trend_statements or [],
                    repair_of=concept, repair_instruction=instruction,
                    seed=seed + attempt)
            except Exception as exc:                      # noqa: BLE001
                # A model failure degrades this concept, never the exploration.
                trace.error = f"{type(exc).__name__}: {exc}"
                trace.attempts = attempt + 1
                return SynthesisResult(None, ConceptValidation(
                    passed=False, attempts=attempt + 1), constraints, trace)

            trace.attempts = attempt + 1
            trace.prompt = getattr(self.provider, "last_prompt", "")
            trace.raw_output = getattr(self.provider, "last_raw", None)
            trace.duration_ms += concept.duration_ms

            validation = self.validator.validate(
                concept, genotype=dna.genotype, program=program, brief=brief,
                constraints=constraints, attempts=attempt + 1)
            codes = [f"{f.code}:{f.field}" for f in validation.findings]
            if attempt == 0:
                trace.findings_before = codes
            else:
                trace.findings_after = codes

            if validation.passed or attempt >= self.max_repairs:
                break
            instruction = validation.repair_instruction()
            trace.repair_instruction = instruction
            trace.repaired = True

        if concept is not None and trace.repaired:
            concept = concept.model_copy(update={"repaired": True,
                                                 "attempts": trace.attempts})
        return SynthesisResult(concept, validation, constraints, trace)
