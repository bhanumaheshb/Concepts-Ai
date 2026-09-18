"""The ONLY module that constructs concrete providers.

Everything else receives protocols. This is what makes `MOCK_MODE=true` a wiring
decision rather than a branch scattered through the engine (spec R-MOCK-02).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import SYNTHESIS_PROVIDERS, Settings, get_settings
from app.creative.mockgen import (
    make_critic_generator, make_phenotype_generator, make_program_generator,
    make_scene_generator,
)
from app.creative.pipeline import Pipeline
from app.creative.synthesis import CreativeSynthesizer
from app.prompt.architectural import ArchitecturalPromptCompiler
from app.prompt.views import ViewPromptCompiler
from app.creative.schemas import CriticLLMOutput, ProgramProposal, SceneGraphProposal
from app.domain.antibrief import AntiBriefProposal
from app.domain.phenotype import ConceptPhenotype
from app.domain.providers.protocols import EmbeddingProvider, ImageProvider, LLMProvider
from app.ontology.graph import Ontology, load_ontology
from app.persistence.repository import InMemoryStore
from app.providers.embeddings.mock import MockEmbeddingProvider, NullEmbeddingProvider
from app.providers.image.mock import MockImageProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.reference.curated import CuratedReferenceAnalyzer
from app.providers.trend.mock import MockTrendProvider
from app.providers.trend.search_backend import (
    HttpSearchBackend, RecordedSearchBackend,
)
from app.providers.trend.web import WebSearchTrendProvider
from app.references.service import ReferenceService
from app.semantics.intelligence import DesignIntelligence
from app.semantics.knowledge import load_knowledge
from app.visual.director import VisualDirector
from app.trends.service import TrendService


@dataclass
class Container:
    settings: Settings
    ontology: Ontology
    llm: LLMProvider
    embeddings: EmbeddingProvider
    images: ImageProvider
    store: InMemoryStore
    pipeline: Pipeline
    references: ReferenceService
    trends: TrendService

    def provider_status(self) -> dict:
        # Who writes the concepts. Reported separately from `llm` because they are
        # different providers: `llm` drives the deterministic internal generators and
        # is always mock by design, while THIS is the one whose prose reaches the user.
        synth = getattr(self.pipeline.synthesizer, "provider", None)
        writer = {"enabled": synth is not None}
        if synth is not None:
            writer.update(
                name=getattr(synth, "name", "?"),
                model=getattr(synth, "model", ""),
                configured=bool(synth.is_configured()),
                missing=list(getattr(synth, "missing_settings", lambda: [])()),
            )
        reasoner = getattr(self.pipeline.intelligence, "reasoner", None)
        director = getattr(self.pipeline.visual_director, "reasoner", None)
        return {
            "design_intelligence": {
                "mode": "llm" if reasoner is not None else "deterministic",
                "provider": getattr(reasoner, "name", None), "model": getattr(reasoner, "model", None),
                "knowledge_version": load_knowledge().version},
            "visual_director": {"mode": "llm-refined" if director is not None else "deterministic",
                                "provider": getattr(director, "name", None)},
            "mock_mode": self.settings.mock_mode,
            "concept_writer": writer,
            "llm": {"name": self.llm.name, "configured": self.llm.is_configured()},
            "embeddings": {"name": self.embeddings.name,
                           "configured": self.embeddings.is_configured()},
            "image": {"name": self.images.name, "configured": self.images.is_configured()},
            "trend_discovery": {"name": self.trends.provider.name,
                                "live": getattr(self.trends.provider, "is_live", False),
                                "mock": getattr(self.trends.provider, "is_mock", True),
                                "configured": self.trends.provider.is_configured(),
                                "fixture_domains": [d.value for d in
                                                    self.trends.provider.domains_available()]},
            "reference_analyzer": {"name": self.references.analyzer.name,
                                   "configured": self.references.analyzer.is_configured(),
                                   "curated": len(self.references.analyzer.known_ids())},
        }


# The phenotype/critic/scene LLM and the CREATIVE SYNTHESIS provider are deliberately
# separate concerns. The deterministic phenotype generator derives its prose from the
# solved genotype and is what the fidelity checks and critics are calibrated against;
# routing it through a hosted or 4B local model would weaken those checks for no
# gain. So LLM_PROVIDER=lmstudio means "synthesise concepts with the local model" and
# leaves the internal generators deterministic.
_SYNTHESIS_ONLY_PROVIDERS = set(SYNTHESIS_PROVIDERS)


def _build_llm(settings: Settings, ont: Ontology) -> LLMProvider:
    if settings.llm_provider not in {"mock"} | _SYNTHESIS_ONLY_PROVIDERS:
        raise RuntimeError(
            f"LLM provider '{settings.llm_provider}' is not implemented. "
            "Use mock | mock_synthesis | cloudflare | lmstudio, or add an adapter "
            "under app/providers/llm/."
        )
    llm = MockLLMProvider(failure_rate=settings.mock_llm_failure_rate)
    llm.register(ConceptPhenotype, make_phenotype_generator(ont))
    llm.register(ProgramProposal, make_program_generator(ont))
    llm.register(CriticLLMOutput, make_critic_generator(ont, settings.mock_critic_policy))
    llm.register(SceneGraphProposal, make_scene_generator(ont))
    llm.register(AntiBriefProposal, lambda ctx, rng: AntiBriefProposal())
    return llm


def _build_embeddings(settings: Settings) -> EmbeddingProvider:
    return MockEmbeddingProvider() if settings.embedding_provider == "mock" else NullEmbeddingProvider()


def _build_images(settings: Settings) -> ImageProvider:
    # Absence of an image configuration is a NORMAL state (spec R-PROV-04).
    return MockImageProvider()


def build_synthesis_provider(settings, ont):
    """The single construction point for creative synthesis.

    Swapping Workers AI for Anthropic, OpenAI or Gemini happens HERE and nowhere else
    — the engine only ever sees the CreativeSynthesisProvider protocol.

    Note that a `cloudflare` provider is returned even with no credentials. It reports
    `is_configured() == False` and raises per concept when called, which is the
    intended behaviour: falling back to the deterministic provider here would print
    mock prose under a real model's name.
    """
    if settings.llm_provider == "cloudflare":
        from app.providers.llm import cloudflare
        return cloudflare.build_provider(
            account_id=settings.cf_account_id, api_token=settings.cf_api_token,
            model=settings.cf_model, base_url=settings.cf_base_url,
            timeout_s=settings.llm_timeout,
            retries=settings.llm_retries,
            max_output_tokens=settings.llm_max_output_tokens)
    if settings.llm_provider == "lmstudio":
        from app.providers.llm import lmstudio
        return lmstudio.build_provider(
            base_url=settings.llm_base_url, model=settings.llm_model,
            api_key=settings.llm_api_key, timeout_s=settings.llm_timeout,
            max_output_tokens=settings.llm_max_output_tokens)
    from app.providers.llm.mock_synthesis import MockCreativeProvider
    return MockCreativeProvider(ont)


def build_reasoning_model(settings):
    """The single construction point for the reasoning model behind Design Intelligence
    and the Visual Director. Any provider with an HttpLLM dialect serves it; the engine
    only sees the StructuredGenerator protocol. None when no real model is configured,
    which is a normal state: both stages then run deterministically and say so."""
    if settings.llm_provider == "lmstudio":
        from app.providers.llm import lmstudio
        client = lmstudio.build_client(base_url=settings.llm_base_url, model=settings.llm_model,
                                       api_key=settings.llm_api_key, timeout_s=settings.llm_timeout)
    elif settings.llm_provider == "cloudflare":
        from app.providers.llm import cloudflare
        client = cloudflare.build_client(account_id=settings.cf_account_id,
                                         api_token=settings.cf_api_token, model=settings.cf_model,
                                         base_url=settings.cf_base_url, timeout_s=settings.llm_timeout)
    else:
        return None
    from app.providers.llm.structured import HttpStructuredGenerator
    return HttpStructuredGenerator(client, name=settings.llm_provider,
                                   max_output_tokens=min(4096, settings.llm_max_output_tokens))


def build_cognition(settings, ont):
    """The ONLY place a conceptual-mutation provider is constructed.

    Returns None when the layer is disabled, which makes the pipeline branch a
    single `is None` check and keeps every recorded baseline reproducible.

    `mock_cognition` is used whenever no synthesis-capable provider is configured:
    it performs the real operations deterministically, so the layer is exercisable
    with no key and no network — the same bargain the rest of mock mode makes.
    """
    if not settings.creative_cognition_enabled:
        return None
    from app.creative_cognition import CognitionConfig, CreativeCognition
    from app.providers.llm.mock_cognition import MockCognitionProvider
    cfg = CognitionConfig(
        budget=settings.creative_cognition_budget,
        max_per_candidate=settings.creative_max_mutations_per_candidate,
        max_generations=settings.creative_max_generations,
        novelty_threshold=settings.creative_novelty_threshold,
    )
    return CreativeCognition(ont, MockCognitionProvider(), cfg)


def build_trend_provider(settings):
    """The single replacement point for trend discovery (§3 of the plan).

    `mock`     — deterministic fixtures, is_live False, banner shown.
    `recorded` — a real corpus over a recorded transport: real URLs, publishers and
                 dates, but is_live stays False because the transport is not live.
    `web`      — a keyed search API. If no key is configured the provider is still
                 returned unconfigured; discovery then reports TREND_DISCOVERY_UNAVAILABLE
                 rather than silently degrading to fixtures and calling them live.
    """
    mode = settings.trend_provider
    if mode == "recorded":
        return WebSearchTrendProvider(
            RecordedSearchBackend(), max_queries=settings.max_trend_queries,
            max_sources=settings.max_sources_per_candidate)
    if mode == "web":
        return WebSearchTrendProvider(
            HttpSearchBackend.for_provider(
                settings.search_backend, settings.search_api_key,
                timeout=settings.search_timeout_s, retries=settings.search_retries),
            max_queries=settings.max_trend_queries,
            max_sources=settings.max_sources_per_candidate)
    return MockTrendProvider()


@lru_cache(maxsize=1)
def get_container() -> Container:
    settings = get_settings()
    ont = load_ontology(settings.ontology_version)
    llm = _build_llm(settings, ont)
    store = InMemoryStore()
    use_llm_critics = settings.mock_critic_policy != "deterministic_only"
    return Container(
        settings=settings, ontology=ont, llm=llm,
        embeddings=_build_embeddings(settings), images=_build_images(settings),
        store=store, pipeline=Pipeline(
            ont, llm, store, use_llm_critics=use_llm_critics,
            synthesizer=(CreativeSynthesizer(
                ont, build_synthesis_provider(settings, ont),
                max_repairs=settings.synthesis_repairs,
                max_workers=settings.synthesis_parallelism)
                if settings.synthesis_enabled else None),
            arch_compiler=(ArchitecturalPromptCompiler(ont)
                           if settings.synthesis_enabled else None),
            view_compiler=(ViewPromptCompiler()
                           if settings.synthesis_enabled else None),
            # Duplicate detection channel 2. Off by default so existing baselines
            # are reproduced exactly; EMBEDDING_PROVIDER=mock turns it on.
            embeddings=(_build_embeddings(settings)
                        if settings.semantic_dedupe else None),
            cognition=build_cognition(settings, ont),
            intelligence=DesignIntelligence(
                load_knowledge(),
                reasoner=build_reasoning_model(settings) if settings.semantic_reasoner_enabled else None),
            visual_director=VisualDirector(
                ont, reasoner=build_reasoning_model(settings) if settings.visual_reasoner_enabled else None)),
        references=ReferenceService(ont, CuratedReferenceAnalyzer(ont)),
        trends=TrendService(ont, build_trend_provider(settings)),
    )
