from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.common import FacetId, Frozen, OntologyRef, Score
from app.domain.genotype import PartialGenotype


class ClicheCluster(Frozen):
    cluster_id: str
    label: str
    facet_values: list[OntologyRef] = Field(min_length=2)
    prevalence: Score
    evidence: Literal["CURATED", "LLM", "ARCHIVE", "REFERENCE"]
    surface_tokens: list[str] = []


class QuestionedAssumption(Frozen):
    assumption_id: str
    statement: str
    inverts_facet: FacetId | None = None
    blocked_by: str | None = None    # set => hard invariant, never offered for inversion


class AntiBrief(Frozen):
    antibrief_id: str
    program_id: str
    cliche_clusters: list[ClicheCluster] = []
    questioned_assumptions: list[QuestionedAssumption] = []
    canonical_seed: PartialGenotype = PartialGenotype()
    canonical_seed_source: str = "cluster"
    generated_by: str | None = None

    def all_cliche_values(self) -> set[str]:
        out: set[str] = set()
        for c in self.cliche_clusters:
            out |= set(c.facet_values)
        return out

    def surface_tokens_excluding(self, occupied: set[str]) -> list[str]:
        """Negative-prompt tokens from clusters this concept does NOT occupy."""
        tokens: list[str] = []
        for c in self.cliche_clusters:
            if len(set(c.facet_values) & occupied) >= 2:
                continue
            tokens.extend(c.surface_tokens)
        seen, out = set(), []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out


# What the LLM actually returns — free text, mapped to ontology refs by code.
class ClicheProposal(Frozen):
    label: str
    elements: list[str] = Field(min_length=2)
    why_predictable: str = ""
    surface_tokens: list[str] = []


class AssumptionProposal(Frozen):
    statement: str
    facet_hint: str | None = None


class AntiBriefProposal(Frozen):
    cliches: list[ClicheProposal] = []
    questioned_assumptions: list[AssumptionProposal] = []
