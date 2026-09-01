"""The default image provider.

Absence of an image configuration is a normal state, never a startup error and
never a degraded-mode warning (spec R-PROV-04). `generate` never raises: it returns
a typed result with the prompt echoed, so the user can always copy it (R-PROV-01).
"""
from __future__ import annotations

from app.domain.images import (
    ImageCapabilities, ImageGenerationRequest, ImageGenerationResult,
)


class MockImageProvider:
    name = "mock"

    def is_configured(self) -> bool:
        return False

    def capabilities(self) -> ImageCapabilities:
        return ImageCapabilities(
            supports_references=False, supports_control_maps=False,
            max_prompt_tokens=None, aspect_ratios=["*"], dialect="GENERIC",
        )

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        return ImageGenerationResult(
            request_id=req.request_id,
            status="NOT_CONFIGURED",
            image=None,
            prompt_echo=req.positive_prompt,
            negative_echo=req.negative_prompt,
            message="No image provider configured. Copy the prompt and generate externally.",
            provider=None, model=None, duration_ms=0,
        )
