"""StructuredGenerator over any HttpLLM dialect.

Everything a reasoning call needs that is NOT domain knowledge lives here:

  * schema enforcement — the pydantic schema is flattened (no $refs) into a grammar the
    serving framework can constrain generation with;
  * validation — the answer must pass the schema's own validation, not merely parse;
  * repair — one retry that states exactly which fields failed;
  * timeouts and transport retries — inherited from HttpLLM;
  * the call record — model, latency, attempts, tokens, success, error.

Failure is RETURNED, never raised and never hidden. A stage that gets `value=None`
falls back to its deterministic path and says so on its own trace.
"""
from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core import logging as elog
from app.domain.providers.protocols import StructuredResult
from app.domain.semantics import LLMCallRecord
from app.providers.llm.http_llm import HttpLLM, LLMTransportError


def flat_schema(model: type[BaseModel], strict: bool = True) -> dict[str, Any]:
    """pydantic JSON schema with every $ref inlined.

    In strict mode every property is required and no extra properties are allowed —
    the form grammar-constrained decoders accept. Defaults on the pydantic side still
    apply when validating, so "required" here only means "the key is emitted".
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out and strict:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)


class HttpStructuredGenerator:
    def __init__(self, client: HttpLLM, *, name: str, validation_retries: int = 1,
                 max_output_tokens: int = 2048) -> None:
        self.client = client
        self.name = name
        self.validation_retries = validation_retries
        self.max_output_tokens = max_output_tokens

    def is_configured(self) -> bool:
        return self.client.is_configured()

    @property
    def model(self) -> str:
        return self.client.model_id

    def generate(self, *, stage: str, purpose: str, system: str, user: str,
                 schema: type[BaseModel], max_output_tokens: int = 2048) -> StructuredResult:
        started = time.perf_counter()
        attempts, error, value = 0, None, None
        tokens_in = tokens_out = None
        prompt = user
        grammar = flat_schema(schema, strict=self.client.strict_schema)
        for attempt in range(self.validation_retries + 1):
            attempts += 1
            try:
                data, _ = self.client.chat_json(
                    system=system, user=prompt, schema=grammar, seed=0,
                    max_tokens=min(max_output_tokens, self.max_output_tokens))
            except LLMTransportError as exc:
                # transport has already retried what is retryable; do not spend more
                error = str(exc)
                break
            usage = (self.client.last_status or {}).get("usage") or {}
            tokens_in = usage.get("prompt_tokens", tokens_in)
            tokens_out = usage.get("completion_tokens", tokens_out)
            try:
                value = schema.model_validate(data)
                error = None
                break
            except ValidationError as exc:
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8])
                error = f"schema validation failed: {problems}"
                prompt = (f"{user}\n\n## YOUR PREVIOUS ANSWER FAILED VALIDATION\n{problems}\n"
                          f"Previous answer (truncated): {json.dumps(data)[:600]}\n"
                          "Return the corrected JSON object only.")
        record = LLMCallRecord(
            stage=stage, purpose=purpose, schema_name=schema.__name__,
            model=self.client.model_id or "", provider=self.name,
            latency_ms=int((time.perf_counter() - started) * 1000), attempts=attempts,
            success=value is not None, error=error,
            input_tokens=tokens_in, output_tokens=tokens_out)
        (elog.note if record.success else elog.warn)(
            f"     llm {stage} {purpose[:40]!r} model={record.model or '?'} "
            f"{record.latency_ms}ms attempts={attempts} "
            f"tokens={tokens_in}/{tokens_out} "
            + ("ok" if record.success else f"FAILED: {(error or '')[:120]}"))
        return StructuredResult(value=value, record=record)
