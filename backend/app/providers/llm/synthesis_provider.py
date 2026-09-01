"""HttpSynthesisProvider -- the vendor-independent half of a synthesis adapter.

Nothing here knows which API is on the other end of the socket. The prompt comes from
`app.creative.synthesis_prompt`, the schema and the tolerant coercion come from
`app.providers.llm.schema`, and the wire comes from an injected `HttpLLM`. A new
vendor is therefore a *client* plus a name, not a new provider class -- which is why
`cloudflare.py` is thirty lines rather than two hundred.
"""
from __future__ import annotations

import time

from app.creative.synthesis_prompt import PROMPT_VERSION, SYSTEM, build_user_prompt
from app.domain.synthesis import StructuredArchitecturalConcept
from app.providers.llm.http_llm import HttpLLM, LLMTransportError
from app.providers.llm.schema import coerce_concept, concept_json_schema


class HttpSynthesisProvider:
    """Implements CreativeSynthesisProvider against any HTTP chat model."""

    def __init__(self, client: HttpLLM, *, name: str,
                 max_output_tokens: int = 3072) -> None:
        self.client = client
        self.name = name
        self.max_output_tokens = max_output_tokens
        self.prompt_version = PROMPT_VERSION
        self.calls = 0
        self.last_raw: dict | None = None
        self.last_prompt: str = ""
        self.last_error: str | None = None

    @property
    def model(self) -> str:
        """A property, not a snapshot: a local server may name the model for us, and
        the debug tab must report what actually answered rather than a blank."""
        return self.client.model_id

    def is_configured(self) -> bool:
        return self.client.is_configured()

    def missing_settings(self) -> list[str]:
        return self.client.missing_settings()

    def synthesize_concept(self, *, concept_dna, brief, program, constraints,
                           reference_context=None, trend_context=None,
                           repair_of=None, repair_instruction: str = "",
                           seed: int = 0) -> StructuredArchitecturalConcept:
        user = build_user_prompt(
            brief=brief, program=program, constraints=constraints,
            genotype=concept_dna.genotype,
            reference_statements=list(reference_context or []),
            trend_statements=list(trend_context or []),
            repair_instruction=repair_instruction,
        )
        self.last_prompt = user
        started = time.time()
        try:
            raw, duration = self.client.chat_json(
                system=SYSTEM, user=user, schema=concept_json_schema(),
                seed=seed, max_tokens=self.max_output_tokens)
        except LLMTransportError as exc:
            # Deliberately NOT caught here. Falling back to the deterministic provider
            # would present mock prose as model output; the pipeline records the
            # failure per concept instead, where it stays visible.
            self.last_error = str(exc)
            raise
        self.calls += 1
        self.last_raw = raw
        concept = coerce_concept(raw)
        return concept.model_copy(update={
            "source": self.name, "model": self.model,
            "duration_ms": duration or int((time.time() - started) * 1000),
            "repaired": bool(repair_instruction),
        })
