"""LM Studio -- a locally served model over its OpenAI-compatible API.

The whole vendor-specific surface is this file. Transport lives in `http_llm.py` and
provider logic in `synthesis_provider.py`, exactly as for Workers AI.

    LLM_PROVIDER=lmstudio
    LLM_BASE_URL=http://localhost:1234   (LM Studio's default server port)
    LLM_MODEL=                            blank => ask the server what it has loaded

Two things differ from a hosted vendor, and both are handled here:

  * **No credentials.** "Configured" therefore means "we know where to look", not
    "we hold a key". A server that is not running is discovered at call time and
    reported per concept, naming the address it tried.
  * **A small model needs the schema enforced, not requested.** `strict_schema`
    asks LM Studio to constrain generation to the concept grammar, which is the
    difference between a 4B model returning a valid object and returning prose
    about one.

The same adapter serves llama.cpp, vLLM and any other OpenAI-compatible local
server; only `LLM_BASE_URL` changes.
"""
from __future__ import annotations

from app.providers.llm.http_llm import HttpLLM
from app.providers.llm.synthesis_provider import HttpSynthesisProvider

DEFAULT_BASE_URL = "http://localhost:1234"
PROVIDER_NAME = "lmstudio"


def build_client(*, base_url: str = DEFAULT_BASE_URL, model: str = "",
                 api_key: str = "", timeout_s: float = 300.0,
                 transport=None) -> HttpLLM:
    """`transport` is injected only by the tests.

    The timeout is generous by hosted standards because a local model on CPU can
    legitimately take minutes for a concept of this size.
    """
    return HttpLLM(
        base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
        model=model.strip(),
        dialect="openai",
        api_key=api_key.strip(),
        timeout_s=timeout_s,
        strict_schema=True,
        transport=transport,
    )


def build_provider(*, base_url: str = DEFAULT_BASE_URL, model: str = "",
                   api_key: str = "", timeout_s: float = 300.0,
                   max_output_tokens: int = 3072,
                   transport=None) -> HttpSynthesisProvider:
    """A CreativeSynthesisProvider backed by a local LM Studio server."""
    return HttpSynthesisProvider(
        build_client(base_url=base_url, model=model, api_key=api_key,
                     timeout_s=timeout_s, transport=transport),
        name=PROVIDER_NAME, max_output_tokens=max_output_tokens)
