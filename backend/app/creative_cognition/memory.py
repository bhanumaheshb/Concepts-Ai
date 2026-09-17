"""Creative memory — structured design facts, never a conversation log.

Its one job is to answer "have I already explored this idea?" so the layer does
not spend budget rediscovering the same move. It holds ids, operations, principles
and outcomes; it never holds model reasoning, and it lives for one exploration
unless the caller chooses to persist it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.cognition import CognitionRecord, CreativeTransformation

_WORD = re.compile(r"[a-z]{4,}")
# Words that carry no design content, so two principles that share only these are
# not the same idea.
_STOP = frozenset({
    "that", "this", "with", "from", "into", "than", "then", "they", "them", "were",
    "will", "would", "could", "should", "have", "been", "being", "which", "while",
    "space", "spatial", "design", "designed", "concept", "architectural", "building",
    "becomes", "rather", "through", "across", "between", "makes", "made", "each",
})


def _signature(text: str) -> frozenset[str]:
    """A principle's content words. Two principles with a high overlap are the same
    idea in different wording, which is exactly what anti-repetition must catch."""
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in _STOP)


@dataclass
class CreativeMemory:
    """Explored ground for one exploration."""
    records: list[CognitionRecord] = field(default_factory=list)
    _signatures: list[frozenset[str]] = field(default_factory=list)
    _principles: list[str] = field(default_factory=list)
    # operation counts, so one operator cannot consume the whole budget
    _op_counts: dict[str, int] = field(default_factory=dict)

    # ---- queries ----------------------------------------------------------
    def is_explored(self, principle: str, threshold: float = 0.6) -> bool:
        """Jaccard over content words. Cheap, deterministic, and independent of the
        embedding provider — semantic duplicate detection at the CONCEPT level is
        still done by diversity.is_duplicate, which this never replaces."""
        sig = _signature(principle)
        if not sig:
            return False
        for prev in self._signatures:
            union = sig | prev
            if union and len(sig & prev) / len(union) >= threshold:
                return True
        return False

    def explored_principles(self, limit: int = 8) -> tuple[str, ...]:
        return tuple(self._principles[-limit:])

    def count_for(self, operation: str) -> int:
        return self._op_counts.get(operation, 0)

    # ---- recording --------------------------------------------------------
    def remember(self, t: CreativeTransformation) -> None:
        self._signatures.append(_signature(t.new_principle))
        self._principles.append(t.new_principle)
        self._op_counts[t.operation.value] = self._op_counts.get(t.operation.value, 0) + 1

    def record(self, rec: CognitionRecord) -> None:
        self.records.append(rec)

    def mark_selected(self, concept_ids: set[str]) -> None:
        """Called after portfolio selection so the trace says which ideas survived."""
        self.records = [
            r.model_copy(update={"selected": True}) if r.child_concept_id in concept_ids else r
            for r in self.records
        ]

    # ---- reporting --------------------------------------------------------
    def summary(self) -> dict:
        applied = [r for r in self.records if r.genotype_status == "APPLIED"]
        return {
            "proposed": len(self.records),
            "applied": len(applied),
            "selected": sum(1 for r in self.records if r.selected),
            "by_operation": dict(sorted(self._op_counts.items())),
            "rejected": sorted({r.rejection_reason for r in self.records
                                if r.rejection_reason}),
        }
