"""REF-00 — resolution.

Order: curated exact → curated alias → analyser → unresolved.
Ambiguity returns candidates. The resolver never silently guesses.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.reference import ReferenceDNA, ReferenceIdentity, ReferenceSelector, ReferenceType

AMBIGUITY_MARGIN = 0.08     # two candidates this close are ambiguous
ACCEPT_THRESHOLD = 0.72


@dataclass
class Resolution:
    dna: ReferenceDNA | None
    candidates: list[ReferenceIdentity]
    ambiguous: bool
    resolved_by: str

    @property
    def ok(self) -> bool:
        return self.dna is not None and not self.ambiguous


class ReferenceResolver:
    def __init__(self, analyzer) -> None:
        self._analyzer = analyzer

    def search(self, query: str, kind: ReferenceType | None = None) -> list[ReferenceIdentity]:
        return self._analyzer.search(query, kind)

    def resolve(self, selector: ReferenceSelector, seed: int = 0) -> Resolution:
        if selector.reference_id:
            dna = self._analyzer.analyse(query=selector.reference_id, kind=selector.kind, seed=seed)
            if dna.identity.reference_id == selector.reference_id:
                return Resolution(dna, [dna.identity], False, "CURATED")

        candidates = self._analyzer.search(selector.query, selector.kind)
        if len(candidates) >= 2:
            top, second = candidates[0], candidates[1]
            # only genuinely ambiguous when BOTH readings are plausible; a field of weak
            # matches is not ambiguity, it is an unresolved query
            if (top.confidence >= ACCEPT_THRESHOLD
                    and top.confidence - second.confidence < AMBIGUITY_MARGIN
                    and top.confidence < 0.95):
                # never guess between two plausible readings — hand both back
                return Resolution(None, candidates, True, "AMBIGUOUS")

        if candidates and candidates[0].confidence >= ACCEPT_THRESHOLD:
            dna = self._analyzer.analyse(
                query=candidates[0].reference_id, kind=candidates[0].kind, seed=seed)
            return Resolution(dna, candidates, False, "CURATED")

        dna = self._analyzer.analyse(query=selector.query, kind=selector.kind, seed=seed)
        return Resolution(dna, candidates, False, dna.identity.resolved_by)
