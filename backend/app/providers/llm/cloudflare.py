"""Cloudflare Workers AI -- endpoint, defaults, and the models worth pointing at.

This is the whole vendor-specific surface. Everything else about synthesis is shared:
the transport lives in `http_llm.py` and the provider logic in `synthesis_provider.py`.

Credentials come from the environment and are never logged:

    LLM_PROVIDER=cloudflare
    CF_ACCOUNT_ID=...        # Workers AI account id
    CF_API_TOKEN=...         # token with the "Workers AI" permission
    CF_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast   (optional)

An account id and token that are absent do NOT disable the synthesis stage. The stage
still runs and fails loudly per concept, because silently degrading to the
deterministic provider would present mock prose as model output.
"""
from __future__ import annotations

from app.providers.llm.http_llm import HttpLLM
from app.providers.llm.synthesis_provider import HttpSynthesisProvider

API_BASE = "https://api.cloudflare.com/client/v4"

# Instruction-tuned models on Workers AI large enough to hold a 21-section
# architectural brief and return schema-valid JSON. The default is the fastest of
# the ones that reliably do both.
DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
SUGGESTED_MODELS = (
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3.1-70b-instruct",
    "@cf/meta/llama-3.1-8b-instruct-fast",
    "@cf/qwen/qwen2.5-coder-32b-instruct",
    "@cf/mistralai/mistral-small-3.1-24b-instruct",
)

PROVIDER_NAME = "cloudflare"


def build_client(*, account_id: str, api_token: str, model: str = "",
                 base_url: str = API_BASE, timeout_s: float = 120.0,
                 transport=None) -> HttpLLM:
    """The Workers AI client. `transport` is injected only by the tests."""
    return HttpLLM(
        base_url=(base_url or API_BASE).rstrip("/"),
        model=model or DEFAULT_MODEL,
        dialect="cloudflare",
        account_id=account_id.strip(),
        api_key=api_token.strip(),
        timeout_s=timeout_s,
        transport=transport,
    )


def build_provider(*, account_id: str, api_token: str, model: str = "",
                   base_url: str = API_BASE, timeout_s: float = 120.0,
                   max_output_tokens: int = 3072,
                   transport=None) -> HttpSynthesisProvider:
    """A CreativeSynthesisProvider backed by Workers AI."""
    return HttpSynthesisProvider(
        build_client(account_id=account_id, api_token=api_token, model=model,
                     base_url=base_url, timeout_s=timeout_s, transport=transport),
        name=PROVIDER_NAME, max_output_tokens=max_output_tokens)
