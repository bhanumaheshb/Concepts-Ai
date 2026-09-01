"""Component versions. Every persisted artefact carries the stamp that produced it
(spec R-VER-01)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "1.0.0"
METRIC_VERSION = "1.0.0"
ALLOCATOR_VERSION = "1.0.0"
MUTATION_VERSION = "1.0.0"
CRITIC_VERSION = "1.0.0"
PROMPT_COMPILER_VERSION = "1.0.0"
SCENE_SCHEMA_VERSION = "1.0.0"


class ModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tier: str
    provider: str
    model: str


class VersionStamp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = SCHEMA_VERSION
    ontology_version: str
    metric_version: str = METRIC_VERSION
    allocator_version: str = ALLOCATOR_VERSION
    mutation_version: str = MUTATION_VERSION
    critic_version: str = CRITIC_VERSION
    prompt_compiler_version: str = PROMPT_COMPILER_VERSION
    scene_schema_version: str = SCENE_SCHEMA_VERSION
    model_routes: list[ModelRoute] = []
