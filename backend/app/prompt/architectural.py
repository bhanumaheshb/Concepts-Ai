"""ArchitecturalPromptCompiler — the terminal artefact (§14/§15).

Deliberately NOT "use the model's description as the prompt". The compiler owns the
section structure and fills each section from the most authoritative source available:
the brief and the genotype outrank the synthesised prose, so a section the model
neglected is still populated from the design that was actually solved.

Every section records where its text came from, which is what makes
"the compiler lost the architecture" a diagnosable claim rather than a suspicion.
"""
from __future__ import annotations

from app.core.hashing import sha256_of
from app.core.ids import deterministic_id
from app.domain.brief import DesignBrief, DesignProgram
from app.domain.concept import ConceptDNA
from app.domain.synthesis import (
    ArchitecturalVisualizationPrompt, ConstraintEnvelope, PromptSection,
    StructuredArchitecturalConcept,
)
from app.ontology.graph import Ontology

COMPILER_VERSION = "2.0.0"

SECTION_ORDER = [
    "SUBJECT", "ARCHITECTURAL CONCEPT", "SITE", "PROGRAM", "SPATIAL ORGANIZATION",
    "ARRIVAL / CIRCULATION", "FOCAL SPACE", "SEATING", "WALKWAY", "STRUCTURE",
    "GEOMETRY", "MASSING", "MATERIALS", "MATERIAL BEHAVIOUR", "LIGHTING", "LANDSCAPE",
    "ATMOSPHERE", "HUMAN SCALE", "CAMERA", "ARCHITECTURAL VISUALIZATION STYLE",
    "CONSTRUCTION REALISM",
]

STYLE = ("architectural visualisation, physically based rendering, accurate daylight "
         "and artificial light balance, correct perspective, believable construction "
         "detail, no illustration styling")

GLOBAL_NEGATIVES = [
    "generic palace", "generic wedding stage", "excessive floral decoration",
    "fantasy architecture", "impossible floating structure", "random columns",
    "generic luxury decor", "unrelated ornament", "copied reference elements",
    "text", "watermark", "logo", "deformed geometry", "warped perspective",
    "duplicated people", "plastic sheen",
]


class ArchitecturalPromptCompiler:
    def __init__(self, ont: Ontology) -> None:
        self.ont = ont

    def _label(self, ref: str) -> str:
        node = self.ont.nodes.get(ref)
        return node.label.lower() if node else ref.split(":")[-1].replace("_", " ")

    def compile(self, *, dna: ConceptDNA, concept: StructuredArchitecturalConcept | None,
                brief: DesignBrief, program: DesignProgram,
                constraints: ConstraintEnvelope,
                scene=None, reference_statements: list[str] | None = None,
                trend_statements: list[str] | None = None,
                extra_negatives: list[str] | None = None,
                aspect_ratio: str = "3:2") -> ArchitecturalVisualizationPrompt:
        g = dna.genotype
        c = concept
        sections: list[PromptSection] = []
        missing: list[str] = []

        def add(name: str, text: str, source: str) -> None:
            text = " ".join((text or "").split())
            if text:
                sections.append(PromptSection(name=name, text=text, source=source))
            else:
                missing.append(name)

        def pick(*candidates: tuple[str, str]) -> tuple[str, str]:
            """First non-empty (text, source). The engine is the fallback, not silence."""
            for text, source in candidates:
                if text and text.strip():
                    return text, source
            return "", "none"

        typology = program.typology.value.replace("_", " ").lower()
        cap = constraints.capacity
        geo_refs = (g.geometry.system if isinstance(g.geometry.system, list)
                    else [g.geometry.system])
        geo = ", ".join(self._label(r) for r in geo_refs)
        primary = next(m for m in g.material_palette if m.role.value == "PRIMARY")
        prim = self._label(primary.material)
        others = [self._label(m.material) for m in g.material_palette
                  if m.material != primary.material]

        # SUBJECT — always from the brief and programme, never from the model
        subject = f"A {typology}"
        if cap:
            subject += f" for {cap} people"
        if constraints.site_dimensions:
            subject += f" on a {constraints.site_dimensions} site"
        if brief.location:
            subject += f", {brief.location}"
        add("SUBJECT", subject, "brief")

        add("ARCHITECTURAL CONCEPT", *pick(
            ((c.concept_thesis if c else ""), "concept"),
            (f"{self._label(g.architectural_language.value)} expressed through "
             f"{self._label(g.structural_logic.value)}", "dna")))

        add("SITE", *pick(
            ((c.landscape if c else ""), "concept"),
            (f"the setting is treated as {self._label(g.site_relationship.value)}", "dna")))

        prog_bits = []
        if c:
            prog_bits = [b for b in (c.program.spatial_hierarchy, c.program.sightlines,
                                     ", ".join(c.program.additional_zones)) if b]
        add("PROGRAM", *pick(
            ("; ".join(prog_bits), "concept"),
            (f"{typology} programme for {cap or 'the stated'} people, arranged as "
             f"{self._label(g.occupation_staging.value)}", "dna")))

        add("SPATIAL ORGANIZATION", *pick(
            ((c.spatial_organization if c else ""), "concept"),
            (f"organised as {geo}", "dna")))

        arrival = ""
        if c:
            arrival = "; ".join(x for x in (c.arrival_sequence, c.circulation) if x)
        add("ARRIVAL / CIRCULATION", *pick(
            (arrival, "concept"),
            (" then ".join(self._label(r) for r in g.spatial_narrative), "dna")))

        focal_name = (c.program.focal_space_label if c and c.program.focal_space_label
                      else "focal space")
        add("FOCAL SPACE", *pick(
            ((c.program.focal_space if c else ""), "concept"),
            (f"a {focal_name} at the centre of the {geo} order", "dna")))
        add("SEATING", *pick(
            ((c.program.seating if c else ""), "concept"),
            (f"seating for {cap} with clear sightlines to the {focal_name}", "dna")))
        add("WALKWAY", *pick(
            ((c.program.walkway if c else ""), "concept"),
            (f"a processional route to the {focal_name}", "dna")))

        add("STRUCTURE", *pick(
            (("; ".join(x for x in (c.structure.structural_system,
                                    c.structure.spans_and_supports,
                                    c.structure.module) if x) if c else ""), "concept"),
            (f"{self._label(g.structural_logic.value)}, built as "
             f"{self._label(g.tectonic_logic.value)}", "dna")))
        add("GEOMETRY", *pick(
            ((c.structure.geometry if c else ""), "concept"), (geo, "dna")))
        add("MASSING", *pick(
            ((c.structure.mass_and_void if c else ""), "concept"),
            (f"massing at {self._label(g.scale_strategy.value)}", "dna")))

        mats = f"{prim} as the primary material"
        if others:
            mats += f", with {', '.join(others)} in secondary roles"
        add("MATERIALS", *pick(
            (((f"{c.materials.primary}; " if c.materials.primary else "")
              + (", ".join(c.materials.secondary))) if c else "", "concept"),
            (mats, "dna")))
        add("MATERIAL BEHAVIOUR", *pick(
            (("; ".join(x for x in (c.materials.material_behaviour,
                                    c.materials.surface_treatment) if x) if c else ""),
             "concept"),
            (f"{prim} left legible as itself, its texture read by raking light", "dna")))

        light_bits = []
        if c:
            light_bits = [x for x in (", ".join(c.lighting.lighting_sources),
                                      c.lighting.colour_temperature,
                                      c.lighting.height_and_distribution,
                                      c.lighting.shadow_behaviour) if x]
        add("LIGHTING", *pick(
            ("; ".join(light_bits), "concept"),
            (f"{self._label(g.lighting_philosophy.value)}", "dna")))

        add("LANDSCAPE", *pick(((c.landscape if c else ""), "concept"),
                               ("planting kept low so the plan stays readable", "dna")))
        add("ATMOSPHERE", *pick(
            ((c.atmosphere if c else ""), "concept"),
            (self._label(g.emotional_register.value), "dna")))
        add("HUMAN SCALE", *pick(
            ((c.human_experience if c else ""), "concept"),
            (f"people at {self._label(g.scale_strategy.value)} for scale", "dna")))

        camera = (c.camera_recommendation.as_phrase() if c else "")
        add("CAMERA", *pick(
            (camera, "concept"),
            ("three-quarter view at 1.6 m eye height, 35 mm lens", "dna")))

        add("ARCHITECTURAL VISUALIZATION STYLE", STYLE, "compiler")
        add("CONSTRUCTION REALISM", *pick(
            ((c.construction_character if c else ""), "concept"),
            (f"assembled as {self._label(g.tectonic_logic.value)} with a believable "
             f"load path", "dna")))

        if reference_statements:
            add("TRANSFERRED PRINCIPLES", "; ".join(reference_statements), "reference")
        if trend_statements:
            add("CURRENT READINGS", "; ".join(trend_statements), "trend")

        ordered = sorted(sections,
                         key=lambda s: (SECTION_ORDER.index(s.name)
                                        if s.name in SECTION_ORDER else 99))
        positive = "\n".join(f"{s.name}: {s.text}" for s in ordered)

        negatives = self._negatives(constraints, concept, extra_negatives)
        return ArchitecturalVisualizationPrompt(
            prompt_id=deterministic_id("avp", dna.concept_id, COMPILER_VERSION),
            concept_id=dna.concept_id,
            sections=ordered, positive_prompt=positive,
            negative_prompt=", ".join(negatives), camera=camera,
            aspect_ratio=aspect_ratio, compiler_version=COMPILER_VERSION,
            inputs_hash=sha256_of({"dna": dna.concept_id,
                                   "concept": c.model_dump(mode="json") if c else None}),
            prompt_hash=sha256_of(positive + "\x00" + ", ".join(negatives)),
            degraded=c is None, missing_sections=missing)

    def _negatives(self, constraints: ConstraintEnvelope,
                   concept: StructuredArchitecturalConcept | None,
                   extra: list[str] | None) -> list[str]:
        """Concept DNA + anti-brief + reference lexicon + the concept's own (§16)."""
        out: list[str] = []
        out += [t.lower() for t in constraints.forbidden_tokens]
        out += [t.lower() for t in (extra or [])]
        if concept:
            out += [a.lower().removeprefix("no ").strip() for a in concept.anti_cliches]
        out += GLOBAL_NEGATIVES
        seen, ordered = set(), []
        for t in out:
            t = " ".join(t.split())
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)
        return ordered
