"""Reference Intelligence entry point: REF-00 → REF-04 in one call.

Produces a CreativePrincipleInjection and nothing else (R-REF-01).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.brief import DesignProgram
from app.domain.reference import (
    CreativePrincipleInjection, ReferenceDNA, ReferenceIdentity, ReferenceRequest,
)
from app.ontology.graph import Ontology
from app.references.injection import build_injection
from app.references.resolver import ReferenceResolver, Resolution


@dataclass
class ReferenceOutcome:
    injection: CreativePrincipleInjection | None
    resolutions: list[Resolution]
    ambiguous: list[list[ReferenceIdentity]]

    @property
    def ok(self) -> bool:
        return self.injection is not None


class ReferenceService:
    def __init__(self, ont: Ontology, analyzer) -> None:
        self.ont = ont
        self.analyzer = analyzer
        self.resolver = ReferenceResolver(analyzer)

    def search(self, query: str, kind=None) -> list[ReferenceIdentity]:
        return self.resolver.search(query, kind)

    def dna(self, reference_id: str, seed: int = 0) -> ReferenceDNA:
        return self.analyzer.analyse(query=reference_id, seed=seed)

    def build(self, request: ReferenceRequest, space=None, seed: int = 0) -> ReferenceOutcome:
        resolutions, dnas, ambiguous = [], [], []
        for sel in request.references:
            res = self.resolver.resolve(sel, seed)
            resolutions.append(res)
            if res.ambiguous:
                ambiguous.append(res.candidates)     # never guess (STEP 4)
            elif res.dna is not None:
                dnas.append(res.dna)
        if ambiguous or not dnas:
            return ReferenceOutcome(None, resolutions, ambiguous)
        return ReferenceOutcome(
            build_injection(self.ont, dnas, request, space, seed), resolutions, [])
