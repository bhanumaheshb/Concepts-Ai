"""ConceptLLMValidator — what the model returned, checked against what was asked.

Invalid output is repaired through one bounded structured retry, never silently
accepted (§18). The checks are deliberately concrete: a field echoing its own name
("seating": "Seating") is the characteristic failure of a small local model, and it
looks like a filled field to any check that only tests for non-empty.
"""
from __future__ import annotations

import re

from app.domain.brief import DesignBrief, DesignProgram
from app.domain.common import Typology
from app.domain.genotype import ConceptGenotype
from app.domain.synthesis import (
    ConceptValidation, ConstraintEnvelope, StructuredArchitecturalConcept,
    ValidationFinding, ValidationSeverity,
)
from app.ontology.graph import Ontology

ERROR, WARNING = ValidationSeverity.ERROR, ValidationSeverity.WARNING

MIN_PROSE = 40          # a thesis or story shorter than this is not a description
MIN_FIELD = 12          # a programme slot shorter than this is a label, not a resolution

REQUIRED_PROSE = [
    ("concept_title", 4), ("concept_thesis", MIN_PROSE), ("design_story", MIN_PROSE),
    ("architectural_language", 20), ("spatial_organization", MIN_PROSE),
    ("arrival_sequence", 25), ("circulation", 25), ("atmosphere", 15),
    ("human_experience", 25), ("construction_character", 25), ("rationale", 25),
]

# Programmes that genuinely need a focal object, seating and a route to it.
GATHERING_TYPOLOGIES = {
    Typology.WEDDING_MANDAP, Typology.EVENT_STAGE, Typology.EXHIBITION,
    Typology.PAVILION,
}

IMPOSSIBLE = re.compile(
    r"\b(floating|levitat\w*|anti-gravity|weightless|hovering)\b", re.I)
SPECULATIVE_OK = ("speculative", "not buildable", "would require", "impossible",
                  "cannot be built", "conceptual only")


def _echoes_name(field: str, value: str) -> bool:
    """'seating': 'Seating' — a label returned in place of a resolution."""
    v = re.sub(r"[^a-z ]", "", value.lower()).strip()
    n = field.replace("_", " ").lower()
    return v in ("", n, n + "s", n.rstrip("s"))


class ConceptLLMValidator:
    def __init__(self, ont: Ontology) -> None:
        self.ont = ont

    def validate(self, concept: StructuredArchitecturalConcept, *,
                 genotype: ConceptGenotype, program: DesignProgram,
                 brief: DesignBrief, constraints: ConstraintEnvelope,
                 attempts: int = 1) -> ConceptValidation:
        f: list[ValidationFinding] = []
        blob = self._blob(concept)

        f += self._required_fields(concept)
        f += self._program_completeness(concept, program)
        f += self._hard_constraints(concept, constraints, blob)
        f += self._dna_consistency(concept, constraints, blob)
        f += self._forbidden(concept, constraints, blob)
        f += self._structure_realism(concept, constraints)
        f += self._spatial_logic(concept)
        f += self._materials_and_light(concept)

        return ConceptValidation(
            passed=not any(x.severity is ERROR for x in f),
            findings=f, attempts=attempts, repaired=concept.repaired)

    # ---------- checks ----------
    def _required_fields(self, c: StructuredArchitecturalConcept):
        out = []
        for field, minimum in REQUIRED_PROSE:
            value = getattr(c, field, "") or ""
            if len(value.strip()) < minimum:
                out.append(ValidationFinding(
                    code="FIELD_TOO_THIN", field=field,
                    message=f"{field} must be a real description "
                            f"(at least {minimum} characters); got {len(value.strip())}.",
                    evidence=value[:80]))
            elif _echoes_name(field, value):
                out.append(ValidationFinding(
                    code="FIELD_ECHOES_NAME", field=field,
                    message=f"{field} repeats its own name instead of describing.",
                    evidence=value[:80]))
        if not c.camera_recommendation.as_phrase():
            out.append(ValidationFinding(
                code="CAMERA_MISSING", field="camera_recommendation",
                message="A camera recommendation is required: viewpoint, height, "
                        "lens and framing."))
        return out

    def _program_completeness(self, c: StructuredArchitecturalConcept,
                              program: DesignProgram):
        """Only the programme the brief actually requires (§6)."""
        out = []
        needed = ["arrival", "circulation", "seating"]
        if program.typology in GATHERING_TYPOLOGIES:
            needed += ["focal_space", "walkway"]
        for slot in needed:
            value = (getattr(c.program, slot, "") or "").strip()
            if len(value) < MIN_FIELD:
                out.append(ValidationFinding(
                    code="PROGRAM_INCOMPLETE", field=f"program.{slot}",
                    message=f"program.{slot} is required for a "
                            f"{program.typology.value.replace('_', ' ').lower()} and "
                            f"must describe it spatially, not name it.",
                    evidence=value[:80]))
            elif _echoes_name(slot, value):
                out.append(ValidationFinding(
                    code="PROGRAM_ECHOES_NAME", field=f"program.{slot}",
                    message=f"program.{slot} returns the label instead of resolving "
                            f"the space.", evidence=value[:80]))
        for zone in program.required_zones:
            name = getattr(zone, "name", str(zone))
            if name and name.lower() not in " ".join(
                    v for v in c.program.model_dump().values() if isinstance(v, str)
            ).lower() + " ".join(c.program.additional_zones).lower():
                out.append(ValidationFinding(
                    code="REQUIRED_ZONE_MISSING", severity=WARNING,
                    field="program", message=f"required zone '{name}' is not resolved."))
        return out

    def _hard_constraints(self, c: StructuredArchitecturalConcept,
                          cons: ConstraintEnvelope, blob: str):
        """The brief is authoritative (§17). A number contradicting it is an error."""
        out = []
        if cons.capacity:
            for found in {int(n.replace(",", "")) for n in
                          re.findall(r"\b(\d{2,5})\s*(?:guests?|people|persons?|seats?|"
                                     r"pax|covers?)\b", blob, re.I)}:
                if found != cons.capacity and abs(found - cons.capacity) > 0:
                    out.append(ValidationFinding(
                        code="CAPACITY_ALTERED", field="program",
                        message=f"capacity is fixed at {cons.capacity}; the concept "
                                f"states {found}.", evidence=str(found)))
        if cons.max_height_m:
            for h in re.findall(r"(\d+(?:\.\d+)?)\s*m(?:etre|eter)?s?\s+(?:tall|high|"
                                r"in height)", blob, re.I):
                if float(h) > cons.max_height_m + 0.01:
                    out.append(ValidationFinding(
                        code="HEIGHT_EXCEEDED", field="structure",
                        message=f"maximum height is {cons.max_height_m}m; the concept "
                                f"states {h}m.", evidence=h))
        return out

    def _dna_consistency(self, c: StructuredArchitecturalConcept,
                         cons: ConstraintEnvelope, blob: str):
        """The identity may be enriched, never replaced (§19)."""
        out = []
        identity = [lf for lf in cons.locked_facets
                    if lf.facet in ("architectural_language", "structural_logic",
                                    "geometry", "material:primary")]
        for lf in identity:
            words = [w for w in re.split(r"[\s_/-]+", lf.label.lower()) if len(w) > 3]
            if words and not any(w in blob for w in words):
                out.append(ValidationFinding(
                    code="DNA_NOT_EXPRESSED", field=lf.facet,
                    message=f"locked {lf.facet} '{lf.label}' is not expressed anywhere "
                            f"in the concept.", evidence=lf.ref))
        # repeating the label verbatim as the whole answer is not interpretation (§9)
        lang = (c.architectural_language or "").strip().lower().rstrip(".")
        for lf in cons.locked_facets:
            if lf.facet == "architectural_language" and lang == lf.label.lower():
                out.append(ValidationFinding(
                    code="DNA_PARROTED", severity=WARNING, field="architectural_language",
                    message="architectural_language repeats the DNA label verbatim "
                            "instead of interpreting it architecturally.",
                    evidence=lf.label))
        return out

    def _forbidden(self, c: StructuredArchitecturalConcept,
                   cons: ConstraintEnvelope, blob: str):
        out = []
        for token in cons.forbidden_tokens:
            if re.search(rf"\b{re.escape(token.lower())}\b", blob):
                out.append(ValidationFinding(
                    code="FORBIDDEN_TOKEN", field="concept",
                    message=f"'{token}' is a forbidden surface token and must not "
                            f"appear.", evidence=token))
        return out

    def _structure_realism(self, c: StructuredArchitecturalConcept,
                           cons: ConstraintEnvelope):
        """Impossible architecture must be flagged, not silently asserted (§10).

        The check must not fire on the engine's OWN vocabulary: `floating_on_water` is
        a pontoon, not levitation, and treating a locked DNA value as an impossibility
        would make the validator reject concepts the engine deliberately chose.
        """
        out = []
        dna_vocab = " ".join(f"{lf.label} {lf.ref} {lf.description}"
                             for lf in cons.locked_facets).lower()
        s = c.structure
        if len((s.structural_system or "").strip()) < 15:
            out.append(ValidationFinding(
                code="STRUCTURE_MISSING", field="structure.structural_system",
                message="the structural system must be described."))
        if len((s.spans_and_supports or "").strip()) < 12:
            out.append(ValidationFinding(
                code="SPANS_MISSING", field="structure.spans_and_supports",
                message="spans and supports must be stated for the structure to be "
                        "checkable."))
        blob = f"{s.structural_system} {s.mass_and_void} {c.design_story}".lower()
        hit = IMPOSSIBLE.search(blob)
        if hit and hit.group(0).lower() not in dna_vocab:
            admitted = any(k in c.construction_character.lower() or k in c.rationale.lower()
                           for k in SPECULATIVE_OK)
            if not admitted:
                out.append(ValidationFinding(
                    code="IMPOSSIBLE_UNFLAGGED", field="construction_character",
                    message="the concept describes structurally impossible architecture "
                            "without acknowledging it in construction_character.",
                    evidence=hit.group(0)))
        return out

    def _spatial_logic(self, c: StructuredArchitecturalConcept):
        out = []
        if len(c.spatial_sequence) < 3:
            out.append(ValidationFinding(
                code="SEQUENCE_MISSING", field="spatial_sequence",
                message="describe how a person moves through the space as at least "
                        "three named steps (e.g. ARRIVAL, COMPRESSION, FOCUS).",
                evidence=str(len(c.spatial_sequence))))
        elif any(len(s.description.strip()) < 12 for s in c.spatial_sequence):
            out.append(ValidationFinding(
                code="SEQUENCE_THIN", severity=WARNING, field="spatial_sequence",
                message="each step in the spatial sequence needs a description."))
        if not c.anti_cliches:
            out.append(ValidationFinding(
                code="ANTI_CLICHES_MISSING", field="anti_cliches",
                message="state what this concept deliberately avoids."))
        return out

    def _materials_and_light(self, c: StructuredArchitecturalConcept):
        out = []
        if len((c.materials.material_behaviour or "").strip()) < 25:
            out.append(ValidationFinding(
                code="MATERIAL_BEHAVIOUR_MISSING", field="materials.material_behaviour",
                message="describe how the material behaves and meets light, not just "
                        "its name."))
        light = c.lighting
        if not light.lighting_sources:
            out.append(ValidationFinding(
                code="LIGHT_SOURCE_MISSING", field="lighting.lighting_sources",
                message="name the light sources."))
        if len((light.height_and_distribution or "").strip()) < 20:
            out.append(ValidationFinding(
                code="LIGHT_DISTRIBUTION_MISSING", field="lighting.height_and_distribution",
                message="state the height and distribution of the light."))
        if not (light.colour_temperature or "").strip():
            out.append(ValidationFinding(
                code="LIGHT_TEMPERATURE_MISSING", severity=WARNING,
                field="lighting.colour_temperature",
                message="state a colour temperature."))
        return out

    @staticmethod
    def _blob(c: StructuredArchitecturalConcept) -> str:
        parts: list[str] = []
        for value in c.model_dump().values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts += [str(v) for v in value]
            elif isinstance(value, dict):
                parts += [str(v) for v in value.values()]
        return " ".join(parts).lower()
