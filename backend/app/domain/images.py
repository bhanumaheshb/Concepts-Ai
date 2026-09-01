"""Image adapter contracts.

These live in `domain` so the *protocol* is available to the API layer without any
engine module ever importing a concrete provider (spec R-SCOPE-02).
"""
from __future__ import annotations

from typing import Literal

from app.domain.common import Frozen


class ImageRef(Frozen):
    image_id: str
    url: str | None = None
    storage_key: str | None = None


class ImageCapabilities(Frozen):
    supports_references: bool = False
    supports_control_maps: bool = False
    max_prompt_tokens: int | None = None
    aspect_ratios: list[str] = ["*"]
    dialect: str = "GENERIC"


class ImageGenerationRequest(Frozen):
    request_id: str
    prompt_id: str
    positive_prompt: str
    negative_prompt: str = ""
    aspect_ratio: str = "3:2"
    seed: int | None = None


class ImageGenerationResult(Frozen):
    request_id: str
    status: Literal["OK", "NOT_CONFIGURED", "FAILED", "RATE_LIMITED", "REFUSED"]
    image: ImageRef | None = None
    prompt_echo: str = ""          # always populated — the user can copy it regardless
    negative_echo: str = ""
    message: str = ""
    provider: str | None = None
    model: str | None = None
    duration_ms: int = 0
