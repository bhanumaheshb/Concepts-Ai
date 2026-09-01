"""Deterministic mock LLM.

This is NOT a stub that returns filler. Each generator derives its output from the
structured context it is handed — above all the phenotype generator, which turns a
solved genotype into readable prose using the ontology's own descriptions. That is
what makes the fidelity checks, the critics and the prompt compiler genuinely
exercised with no network (spec R-MOCK-01).
"""
from __future__ import annotations

import time
from typing import Callable

from pydantic import BaseModel

from app.core.seeded import SeededRandom
from app.domain.common import ModelTier
from app.domain.providers.protocols import (
    ModelRef, PromptEnvelope, ProviderSchemaError, StructuredResponse, Usage,
)

Generator = Callable[[BaseModel | None, SeededRandom], BaseModel]


class MockLLMProvider:
    name = "mock"

    def __init__(self, failure_rate: float = 0.0) -> None:
        self._generators: dict[str, Generator] = {}
        self.failure_rate = failure_rate
        self.calls: list[str] = []

    def register(self, schema: type[BaseModel], gen: Generator) -> None:
        self._generators[schema.__name__] = gen

    def is_configured(self) -> bool:
        return True

    def complete_structured(
        self, *, envelope: PromptEnvelope, schema: type[BaseModel],
        seed: int = 0, context: BaseModel | None = None,
    ) -> StructuredResponse:
        started = time.perf_counter()
        self.calls.append(envelope.prompt_id)
        gen = self._generators.get(schema.__name__)
        if gen is None:
            raise ProviderSchemaError(f"no mock generator registered for {schema.__name__}")
        rng = SeededRandom(seed, envelope.prompt_id, schema.__name__)
        attempts = 1
        # deterministic injected failures, so a failing repair-path test is reproducible
        if self.failure_rate > 0 and rng.substream("fail").random() < self.failure_rate:
            attempts = 2
        value = gen(context, rng)
        prompt_chars = sum(len(b.text) for b in envelope.blocks)
        cached = sum(len(b.text) for b in envelope.blocks if b.cacheable)
        return StructuredResponse(
            value=value,
            usage=Usage(tokens_in=prompt_chars // 4, tokens_out=400, cached_in=cached // 4),
            model=ModelRef(provider="mock", model=f"mock-{envelope.tier.value.lower()}",
                           tier=envelope.tier, is_mock=True),
            duration_ms=int((time.perf_counter() - started) * 1000),
            attempts=attempts,
        )
