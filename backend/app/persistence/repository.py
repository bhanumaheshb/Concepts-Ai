"""Repository protocol + in-memory implementation.

Postgres is not required for the first vertical slice. Adding it later means one
new implementation and one line in composition.py — no engine change.
"""
from __future__ import annotations

from typing import Protocol

from app.domain.concept import ConceptDNA
from app.domain.genotype import ConceptGenotype


class ExplorationStore(Protocol):
    def put(self, record) -> None: ...
    def get(self, exploration_id: str): ...
    def list_ids(self) -> list[str]: ...
    def get_concept(self, concept_id: str) -> ConceptDNA | None: ...
    def archive_genotypes(self, typology: str,
                          exclude_exploration_id: str | None = None) -> list[ConceptGenotype]: ...
    def add_to_archive(self, typology: str, exploration_id: str,
                       genotypes: list[ConceptGenotype]) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, object] = {}
        self._concepts: dict[str, ConceptDNA] = {}
        self._archive: dict[str, list[tuple[str, ConceptGenotype]]] = {}
        self._feedback: list[dict] = []
        self._trends: dict[str, object] = {}

    def put(self, record) -> None:
        self._records[record.exploration_id] = record
        for c in record.all_concepts():
            self._concepts[c.concept_id] = c

    def get(self, exploration_id: str):
        return self._records.get(exploration_id)

    def list_ids(self) -> list[str]:
        return list(self._records.keys())

    def get_concept(self, concept_id: str) -> ConceptDNA | None:
        return self._concepts.get(concept_id)

    def archive_genotypes(self, typology: str,
                          exclude_exploration_id: str | None = None) -> list[ConceptGenotype]:
        return [g for eid, g in self._archive.get(typology, [])
                if eid != exclude_exploration_id]

    def add_to_archive(self, typology: str, exploration_id: str,
                       genotypes: list[ConceptGenotype]) -> None:
        bucket = self._archive.setdefault(typology, [])
        bucket[:] = [(eid, g) for eid, g in bucket if eid != exploration_id]
        bucket.extend((exploration_id, g) for g in genotypes)

    def put_trend(self, result) -> None:
        self._trends[result.result_id] = result

    def get_trend(self, result_id: str):
        return self._trends.get(result_id)

    def add_feedback(self, payload: dict) -> None:
        self._feedback.append(payload)

    def feedback(self) -> list[dict]:
        return list(self._feedback)
