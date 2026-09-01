"""Deterministic pseudo-embeddings, seeded by content hash and unit-normalised.

Exercises the channel-2 plumbing without pretending to semantic behaviour.
"""
from __future__ import annotations

import hashlib
import math
from typing import Sequence


class MockEmbeddingProvider:
    name = "mock"
    dimensions = 64

    def is_configured(self) -> bool:
        return True

    def embed_text(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            raw = [(h[i % len(h)] / 255.0) - 0.5 for i in range(self.dimensions)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            out.append([round(v / norm, 6) for v in raw])
        return out


class NullEmbeddingProvider:
    name = "none"
    dimensions = 0

    def is_configured(self) -> bool:
        return False

    def embed_text(self, texts: Sequence[str]) -> list[list[float]]:
        return [[] for _ in texts]
