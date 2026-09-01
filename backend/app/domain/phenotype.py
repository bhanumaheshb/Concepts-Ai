"""The phenotype: the human-readable expression of a genotype.

Generated *from* a solved genotype. Never the source of a design decision.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.common import Frozen


class RationaleLink(Frozen):
    move: str
    because: str
    evidence_ref: str          # MUST resolve to a Constraint id or a program.* path


class PrecedentNote(Frozen):
    reference: str
    used_as: Literal["PRINCIPLE", "TYPOLOGY", "MOTIF"] = "PRINCIPLE"
    not_copied: str = ""


class VisualDirection(Frozen):
    atmosphere: str
    key_moment: str
    depiction_register: Literal[
        "ARCHITECTURAL_PHOTO", "CINEMATIC", "DIAGRAMMATIC", "PAINTERLY"
    ] = "ARCHITECTURAL_PHOTO"
    palette_words: list[str] = Field(min_length=2, max_length=6)
    avoid_terms: list[str] = []


class ConceptPhenotype(Frozen):
    title: str = Field(max_length=64)
    one_line: str = Field(max_length=200)
    design_thesis: str
    spatial_explanation: str
    material_explanation: str
    experience_narrative: str
    rationale_chain: list[RationaleLink] = Field(min_length=2)
    precedent_notes: list[PrecedentNote] = []
    what_it_is_not: str = ""
    reconciliation_thesis: str | None = None
    signature_read: str = Field(max_length=40)   # "hovering", "sunken", "woven"
    visual_direction: VisualDirection
