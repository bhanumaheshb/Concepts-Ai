"""Provider protocols. The ONLY provider-facing module an engine package may import.

Note what is deliberately absent from the LLM signature: `temperature`, `top_p`.
Creativity in this system does not come from sampling noise, so the parameter is
not plumbed at all (spec critical rule 3).
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.domain.common import Frozen, ModelTier
from app.domain.images import ImageCapabilities, ImageGenerationRequest, ImageGenerationResult

T = TypeVar("T", bound=BaseModel)


class PromptBlock(Frozen):
    role: str            # system | user | assistant
    text: str
    cacheable: bool = False


class PromptEnvelope(Frozen):
    """Prompts are versioned artefacts, not f-strings scattered through the code."""
    prompt_id: str
    version: str
    blocks: list[PromptBlock]
    schema_ref: str
    tier: ModelTier
    max_output_tokens: int = 4096
    timeout_s: float = 90.0


class Usage(Frozen):
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0


class ModelRef(Frozen):
    provider: str
    model: str
    tier: ModelTier
    is_mock: bool = False


class StructuredResponse(Frozen):
    value: Any
    usage: Usage = Usage()
    model: ModelRef
    stop_reason: str = "end_turn"
    duration_ms: int = 0
    attempts: int = 1


class ProviderRefusal(RuntimeError):
    pass


class ProviderSchemaError(RuntimeError):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def complete_structured(
        self,
        *,
        envelope: PromptEnvelope,
        schema: type[T],
        seed: int = 0,
        context: BaseModel | None = None,
    ) -> StructuredResponse:
        """`context` carries the same information the prompt blocks already contain,
        in structured form. Real providers MUST ignore it — it exists so that a mock
        provider can return output faithful to the actual genotype rather than
        lorem ipsum, which is what makes mock mode exercise the real pipeline."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def is_configured(self) -> bool: ...

    def embed_text(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class TrendDiscoveryProvider(Protocol):
    """Returns structured trend candidates. The ranking, selection and creative layers
    are provider-independent: swapping a live web provider in must not touch them."""
    name: str
    is_live: bool

    def is_configured(self) -> bool: ...

    def discover(self, *, queries: Sequence[str], domain: object,
                 limit: int, seed: int = 0) -> list[object]:
        """-> list[TrendCandidate] for one domain."""
        ...


@runtime_checkable
class ReferenceAnalyzerProvider(Protocol):
    """Produces ReferenceDNA. The engine consumes only ReferenceDNA and
    CreativePrincipleInjection and knows nothing about who produced them."""
    name: str

    def is_configured(self) -> bool: ...

    def known_ids(self) -> list[str]: ...

    def search(self, query: str, kind: object | None = None) -> list[object]:
        """-> list[ReferenceIdentity]. Ambiguity returns candidates, never a guess."""
        ...

    def analyse(self, *, query: str, kind: object | None = None, seed: int = 0) -> object:
        """-> ReferenceDNA."""
        ...


@runtime_checkable
class ImageProvider(Protocol):
    """Never imported by the creative engine. Reached only through this protocol."""
    name: str

    def is_configured(self) -> bool: ...

    def capabilities(self) -> ImageCapabilities: ...

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult: ...


@runtime_checkable
class CreativeSynthesisProvider(Protocol):
    """Turns ONE solved Concept DNA into a structured architectural concept.

    Provider-independent by construction: Cloudflare Workers AI, Anthropic, OpenAI or
    Gemini each implement this same pair. Nothing about a vendor or its wire format
    appears in the signature.

    The provider is handed a concept that has ALREADY been decided. It expresses that
    concept; it does not choose one, and it never sees the other nine — diversity is
    the engine's job and is settled before this call (§1).
    """
    name: str
    model: str

    def is_configured(self) -> bool: ...

    def synthesize_concept(
        self,
        *,
        concept_dna: Any,
        brief: Any,
        program: Any,
        constraints: Any,
        reference_context: Any | None = None,
        trend_context: Any | None = None,
        repair_of: Any | None = None,
        repair_instruction: str = "",
        seed: int = 0,
    ) -> Any:
        """-> StructuredArchitecturalConcept."""
        ...


class SearchError(RuntimeError):
    """A search backend could not answer.

    Lives in the domain because it is part of the provider CONTRACT: the trend service
    must be able to tell an outage from an empty result set without importing a
    concrete backend. (tests/test_architecture.py enforces that it cannot.)
    """
