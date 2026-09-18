"""Runtime configuration. Every value has a default that requires no API key."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


def _load_dotenv() -> None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.split("#")[0].strip())
        return


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# Providers that run the creative-synthesis stage. `mock` is absent on purpose: it
# means "the pre-synthesis engine, unchanged", not "synthesis that does nothing".
SYNTHESIS_PROVIDERS = ("cloudflare", "lmstudio", "mock_synthesis")


class Settings(BaseModel):
    mock_mode: bool = True
    llm_provider: str = "mock"
    embedding_provider: str = "mock"
    semantic_dedupe_enabled: bool = False   # channel 2; see Settings.semantic_dedupe
    image_provider: str = "none"
    engine_seed: int = 42
    ontology_version: str = "v1"
    default_k: int = 10
    mock_llm_failure_rate: float = 0.0
    mock_critic_policy: str = "deterministic_only"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]
    # --- LLM creative synthesis ---
    # mock            : no synthesis stage at all — the pre-synthesis engine, unchanged
    # mock_synthesis  : deterministic synthesis, no model, no network
    # cloudflare      : Cloudflare Workers AI (CF_ACCOUNT_ID + CF_API_TOKEN)
    # lmstudio        : a local OpenAI-compatible server (LLM_BASE_URL)
    cf_account_id: str = ""
    cf_api_token: str = ""
    cf_model: str = ""                    # "" => the adapter's default
    cf_base_url: str = "https://api.cloudflare.com/client/v4"
    llm_base_url: str = "http://localhost:1234"   # LM Studio's default port
    llm_model: str = ""                   # "" => ask the local server what it loaded
    llm_api_key: str = ""                 # local servers ignore this
    llm_timeout: float = 300.0            # a local model on CPU can take minutes
    llm_max_output_tokens: int = 8192   # the full concept schema does not fit in 3072
    synthesis_repairs: int = 1
    synthesis_parallelism: int = 5
    llm_retries: int = 0
    # --- creative cognition (conceptual exploration layer) ---
    # OFF by default: enabling it adds candidates and LLM calls, so every
    # recorded baseline was captured with it disabled.
    # Design Intelligence: a reasoning model reads the brief before the creative search.
    # Off => the deterministic reading, which the trace labels as such.
    semantic_reasoner_enabled: bool = False
    # Visual Director refinement of the hero image by a reasoning model. Off by default:
    # one call per concept is expensive on a local model and direction is complete without it.
    visual_reasoner_enabled: bool = False
    creative_cognition_enabled: bool = False
    creative_cognition_budget: int = 8
    creative_max_mutations_per_candidate: int = 2
    creative_max_generations: int = 1
    # No sampling-noise knob by design: the repository forbids plumbing
    # temperature/top_p/top_k through engine interfaces (critical rule 3, enforced
    # by tests/test_architecture.py). Exploration breadth is set by the operations
    # and the budget above; a concrete provider may configure decoding internally.
    creative_novelty_threshold: float = 0.6
    creative_synthesis: bool | None = None   # None => derived from llm_provider

    @property
    def synthesis_enabled(self) -> bool:
        """Note that an UNCONFIGURED provider still enables the stage.

        Disabling it on a missing key, or on a local server that happens to be down,
        would quietly hand back engine-only concepts that look like a successful run.
        Failing per concept says what went wrong.
        """
        if self.creative_synthesis is not None:
            return self.creative_synthesis
        return self.llm_provider in SYNTHESIS_PROVIDERS

    # --- trend discovery ---
    trend_provider: str = "mock"          # mock | recorded | web
    search_backend: str = "none"          # none | brave | tavily | serper
    search_api_key: str = ""
    max_trend_queries: int = 12
    max_trend_candidates: int = 24
    max_sources_per_candidate: int = 6
    search_timeout_s: float = 8.0
    search_retries: int = 2
    trend_fetch_pages: bool = False

    @property
    def trend_live(self) -> bool:
        """Live means: the transport really goes to the web. `recorded` replays real
        evidence over a recorded transport and is deliberately NOT live."""
        return self.trend_provider == "web"

    @property
    def embeddings_enabled(self) -> bool:
        return self.embedding_provider != "none"

    @property
    def semantic_dedupe(self) -> bool:
        """Duplicate-detection channel 2 — "the same idea in different facets".

        Defaults OFF even when an embedding provider exists, because switching it on
        can only ADD rejections (spec R-DIV-02) and would therefore move the recorded
        no-reference baselines. Set SEMANTIC_DEDUPE=true to enable.
        """
        return self.semantic_dedupe_enabled and self.embeddings_enabled

    @property
    def image_configured(self) -> bool:
        return self.image_provider not in ("", "none", "mock")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    e = os.environ.get
    return Settings(
        mock_mode=_b("MOCK_MODE", True),
        llm_provider=e("LLM_PROVIDER", "mock"),
        embedding_provider=e("EMBEDDING_PROVIDER", "mock"),
        semantic_dedupe_enabled=_b("SEMANTIC_DEDUPE", False),
        image_provider=e("IMAGE_PROVIDER", "none"),
        engine_seed=int(e("ENGINE_SEED", "42")),
        ontology_version=e("ONTOLOGY_VERSION", "v1"),
        default_k=int(e("DEFAULT_K", "10")),
        mock_llm_failure_rate=float(e("MOCK_LLM_FAILURE_RATE", "0.0")),
        mock_critic_policy=e("MOCK_CRITIC_POLICY", "deterministic_only"),
        api_port=int(e("API_PORT", "8000")),
        cors_origins=[o.strip() for o in e("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
        cf_account_id=e("CF_ACCOUNT_ID", "").strip(),
        cf_api_token=e("CF_API_TOKEN", "").strip(),
        cf_model=e("CF_MODEL", "").strip(),
        cf_base_url=e("CF_BASE_URL", "https://api.cloudflare.com/client/v4").rstrip("/"),
        llm_base_url=e("LLM_BASE_URL", "http://localhost:1234").rstrip("/"),
        llm_model=e("LLM_MODEL", "").strip(),
        llm_api_key=e("LLM_API_KEY", "").strip(),
        llm_timeout=float(e("LLM_TIMEOUT", "300")),
        llm_max_output_tokens=int(e("LLM_MAX_OUTPUT_TOKENS", "8192")),
        synthesis_repairs=int(e("SYNTHESIS_REPAIRS", "1")),
        synthesis_parallelism=max(1, min(10, int(e("SYNTHESIS_PARALLELISM", "5")))),
        llm_retries=max(0, int(e("LLM_RETRIES", "0"))),
        semantic_reasoner_enabled=_b("SEMANTIC_REASONER_ENABLED", False),
        visual_reasoner_enabled=_b("VISUAL_REASONER_ENABLED", False),
        creative_cognition_enabled=_b("CREATIVE_COGNITION_ENABLED", False),
        creative_cognition_budget=int(e("CREATIVE_COGNITION_BUDGET", "8")),
        creative_max_mutations_per_candidate=int(e("CREATIVE_MAX_MUTATIONS_PER_CANDIDATE", "2")),
        creative_max_generations=int(e("CREATIVE_MAX_GENERATIONS", "1")),
        creative_novelty_threshold=float(e("CREATIVE_NOVELTY_THRESHOLD", "0.6")),
        # A blank CREATIVE_SYNTHESIS= line means "not set", not "off". `.env.example`
        # ships the key empty, and reading that as False would silently disable
        # synthesis for anyone who copied it — the failure this layer exists to avoid.
        creative_synthesis=(None if not (e("CREATIVE_SYNTHESIS") or "").strip()
                            else _b("CREATIVE_SYNTHESIS", False)),
        trend_provider=e("TREND_PROVIDER", "mock").strip().lower(),
        search_backend=e("SEARCH_BACKEND", "none").strip().lower(),
        search_api_key=e("SEARCH_API_KEY", "").strip(),
        max_trend_queries=int(e("MAX_TREND_QUERIES", "12")),
        max_trend_candidates=int(e("MAX_TREND_CANDIDATES", "24")),
        max_sources_per_candidate=int(e("MAX_SOURCES_PER_CANDIDATE", "6")),
        search_timeout_s=float(e("SEARCH_TIMEOUT_S", "8.0")),
        search_retries=int(e("SEARCH_RETRIES", "2")),
        trend_fetch_pages=_b("TREND_FETCH_PAGES", False),
    )
