from __future__ import annotations

from pydantic import Field

from app.domain.common import FacetId, Frozen, OntologyRef, Score


class ValuePrior(Frozen):
    value: OntologyRef
    # ceiling is 4.0, not 1.0: reference prior bias multiplies this and a 1.0 cap would
    # discard the multiplier entirely. Unbiased weights never exceed 0.87, so the wider
    # bound is a no-op for a non-reference run.
    weight: float = Field(ge=0.0, le=4.0)


class Exclusion(Frozen):
    value: OntologyRef
    rule_id: str
    reason: str


class FacetDomain(Frozen):
    facet_id: FacetId
    legal: list[ValuePrior]
    excluded: list[Exclusion] = []

    def values(self) -> list[str]:
        return [v.value for v in self.legal]

    def weights(self) -> list[float]:
        return [v.weight for v in self.legal]


class TensionPair(Frozen):
    a: OntologyRef
    b: OntologyRef
    weight: float


class CreativeSearchSpace(Frozen):
    space_id: str
    program_id: str
    ontology_version: str
    domains: list[FacetDomain]
    tensions: list[TensionPair] = []
    relaxations_applied: list[str] = []
    effective_dimensionality: float = 0.0

    def domain(self, facet: FacetId) -> FacetDomain:
        for d in self.domains:
            if d.facet_id == facet:
                return d
        raise KeyError(f"no domain for facet {facet}")

    def legal(self, facet: FacetId) -> list[str]:
        try:
            return self.domain(facet).values()
        except KeyError:
            return []

    def is_legal(self, facet: FacetId, value: str) -> bool:
        return value in self.legal(facet)
