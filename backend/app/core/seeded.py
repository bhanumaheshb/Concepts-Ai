"""Deterministic randomness.

Every stochastic decision in the engine draws from a SeededRandom substream.
There is no call to a global RNG or to the clock anywhere in the engine, which is
what makes an exploration byte-reproducible for a given seed (spec R-ALLOC-01).
"""
from __future__ import annotations

import hashlib
import random
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


class SeededRandom:
    def __init__(self, seed: int, *labels: object) -> None:
        self.seed = seed
        self.labels = tuple(str(x) for x in labels)
        self._rng = random.Random(self._derive(seed, self.labels))

    @staticmethod
    def _derive(seed: int, labels: tuple[str, ...]) -> int:
        payload = f"{seed}:" + "|".join(labels)
        return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")

    def substream(self, *labels: object) -> "SeededRandom":
        return SeededRandom(self.seed, *self.labels, *labels)

    def random(self) -> float:
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        return seq[self._rng.randrange(len(seq))]

    def shuffled(self, seq: Iterable[T]) -> list[T]:
        items = list(seq)
        self._rng.shuffle(items)
        return items

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        total = sum(max(0.0, w) for w in weights)
        if total <= 0:
            return self.choice(items)
        r = self._rng.random() * total
        acc = 0.0
        for item, w in zip(items, weights):
            acc += max(0.0, w)
            if r <= acc:
                return item
        return items[-1]

    def sample_without_replacement(self, items: Sequence[T], weights: Sequence[float], k: int) -> list[T]:
        pool, wts, out = list(items), list(weights), []
        for _ in range(min(k, len(pool))):
            pick = self.weighted_choice(pool, wts)
            idx = pool.index(pick)
            pool.pop(idx)
            wts.pop(idx)
            out.append(pick)
        return out
