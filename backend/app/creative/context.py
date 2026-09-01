"""Structured context handed to providers alongside the rendered prompt.

Real providers ignore this; the prompt blocks already contain the same information
in prose. It exists so a mock provider can return output faithful to the actual
genotype instead of filler.
"""
from __future__ import annotations

from app.domain.brief import DesignProgram
from app.domain.common import Frozen, NicheRole
from app.domain.concept import ConceptDNA
from app.domain.genotype import ConceptGenotype


class PhenotypeContext(Frozen):
    genotype: ConceptGenotype
    program: DesignProgram
    role: NicheRole
    principle_statements: list[str] = []
    forbidden_tokens: list[str] = []
    sibling_titles: list[str] = []
    preserve_title: str | None = None
    preserve_signature: str | None = None
    fix_notes: list[str] = []


class CriticContext(Frozen):
    concept: ConceptDNA
    program: DesignProgram
    critic: str


class SceneContext(Frozen):
    genotype: ConceptGenotype
    program: DesignProgram


class BriefContext(Frozen):
    raw_text: str
    typology: str
