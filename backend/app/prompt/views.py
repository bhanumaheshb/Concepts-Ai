"""Per-area image prompts for one concept — the shot list.

One concept becomes several prompts: the mandap, the entrance, the walkway, the
seating, the dance floor, the bar counter. Each is a different camera on the SAME
venue, which is the whole difficulty: six prompts that each describe a different
place but must render as one building.

That is solved structurally rather than by asking nicely. Every view reuses the
concept's identity sections — architectural concept, structure, geometry, materials,
material behaviour, lighting, landscape, atmosphere, style, construction realism —
**byte for byte** from the hero prompt. Only SUBJECT, AREA, HUMAN SCALE and CAMERA
change. `shared_signature` hashes those identity sections, so "these six images belong
together" is a value you can compare, and `tests/test_views.py` asserts it is
identical across a concept's views and different between concepts.

The area list is derived, not hardcoded per brief: it comes from the typology's
canonical shot list, extended by whatever additional zones the programme or the model
actually named. A concept with no bar does not get a bar prompt.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.hashing import sha256_of
from app.core.ids import deterministic_id
from app.domain.brief import DesignProgram
from app.domain.concept import ConceptDNA
from app.domain.synthesis import (
    ArchitecturalVisualizationPrompt, PromptSection, StructuredArchitecturalConcept,
)

VIEWS_VERSION = "1.0.0"

# Sections that make two images look like the same place. Copied verbatim into every
# view; never regenerated per view, because regenerating is how a set drifts apart.
IDENTITY_SECTIONS = (
    "ARCHITECTURAL CONCEPT", "SITE", "STRUCTURE", "GEOMETRY", "MASSING",
    "MATERIALS", "MATERIAL BEHAVIOUR", "LIGHTING", "LANDSCAPE", "ATMOSPHERE",
    "ARCHITECTURAL VISUALIZATION STYLE", "CONSTRUCTION REALISM",
    "TRANSFERRED PRINCIPLES", "CURRENT READINGS",
)

# Order within a single view prompt.
VIEW_SECTION_ORDER = (
    "SUBJECT", "AREA", "ARCHITECTURAL CONCEPT", "SITE", "SPATIAL ORGANIZATION",
    "STRUCTURE", "GEOMETRY", "MASSING", "MATERIALS", "MATERIAL BEHAVIOUR",
    "LIGHTING", "LANDSCAPE", "ATMOSPHERE", "HUMAN SCALE", "CAMERA",
    "ARCHITECTURAL VISUALIZATION STYLE", "CONSTRUCTION REALISM",
    "TRANSFERRED PRINCIPLES", "CURRENT READINGS",
)


@dataclass(frozen=True)
class ViewSpec:
    key: str
    label: str
    source_section: str = ""      # hero-prompt section carrying this area's text
    aliases: tuple[str, ...] = ()  # matched against programme / model zone names
    camera: str = ""
    optional: bool = False         # included only when the concept actually names it


def _v(key, label, section="", aliases=(), camera="", optional=False) -> ViewSpec:
    return ViewSpec(key=key, label=label, source_section=section, aliases=aliases,
                    camera=camera, optional=optional)


# The canonical shot list per typology. Optional views appear only when the programme
# or the model names them, so a ceremony with no bar does not get an invented one.
VIEW_CATALOGUE: dict[str, tuple[ViewSpec, ...]] = {
    "WEDDING_MANDAP": (
        _v("entrance", "Entrance", "ARRIVAL / CIRCULATION", ("entry", "arrival", "gate"),
           "eye-level three-quarter view at the threshold, 28 mm lens, looking in"),
        _v("walkway", "Walkway", "WALKWAY", ("aisle", "processional", "path"),
           "low eye-level along the processional axis, 35 mm lens, one-point perspective"),
        _v("mandap", "Mandap", "FOCAL SPACE", ("ceremony", "canopy", "stage"),
           "frontal hero view, 35 mm lens, the canopy centred and complete in frame"),
        _v("seating", "Seating", "SEATING", ("guest seating", "audience"),
           "raised three-quarter view across the seating, 24 mm lens"),
        _v("dance_floor", "Dance Floor", "", ("dance", "sangeeth", "performance"),
           "wide view across the dance floor at 1.6 m, 24 mm lens, evening light",
           optional=True),
        _v("bar", "Bar Counter", "", ("bar", "counter", "beverage"),
           "three-quarter view of the bar counter, 50 mm lens, close",
           optional=True),
    ),
    "EVENT_STAGE": (
        _v("entrance", "Entrance", "ARRIVAL / CIRCULATION", ("entry", "arrival"),
           "eye-level three-quarter view at the threshold, 28 mm lens"),
        _v("walkway", "Walkway", "WALKWAY", ("aisle", "path"),
           "low eye-level along the approach, 35 mm lens"),
        _v("stage", "Stage", "FOCAL SPACE", ("stage", "platform"),
           "frontal hero view, 35 mm lens, the stage centred"),
        _v("audience", "Audience", "SEATING", ("audience", "seating"),
           "raised three-quarter view over the audience, 24 mm lens"),
        _v("bar", "Bar Counter", "", ("bar", "counter"),
           "three-quarter view of the bar counter, 50 mm lens", optional=True),
    ),
    "RESTAURANT": (
        _v("entry", "Entry", "ARRIVAL / CIRCULATION", ("entry", "arrival"),
           "eye-level view at the door, 28 mm lens, looking in"),
        _v("dining", "Dining", "SEATING", ("dining", "covers", "tables"),
           "three-quarter view across the dining room at 1.4 m, 24 mm lens"),
        _v("bar", "Bar Counter", "", ("bar", "counter"),
           "three-quarter view of the bar counter, 50 mm lens"),
        _v("focal", "Open Kitchen", "FOCAL SPACE", ("kitchen", "pass"),
           "frontal view of the pass, 35 mm lens", optional=True),
    ),
    "PAVILION": (
        _v("approach", "Approach", "ARRIVAL / CIRCULATION", ("approach", "arrival"),
           "distant three-quarter view on approach, 35 mm lens"),
        _v("threshold", "Threshold", "WALKWAY", ("threshold", "entry"),
           "eye-level view at the threshold, 28 mm lens"),
        _v("interior", "Interior", "FOCAL SPACE", ("interior", "centre", "void"),
           "interior view looking up and out, 24 mm lens"),
        _v("seating", "Seating", "SEATING", ("seating", "rest"),
           "three-quarter view across the seating, 35 mm lens", optional=True),
    ),
    "EXHIBITION": (
        _v("entry", "Entry", "ARRIVAL / CIRCULATION", ("entry", "arrival"),
           "eye-level view at the entry, 28 mm lens"),
        _v("circulation", "Circulation", "WALKWAY", ("circulation", "route"),
           "low eye-level along the route, 35 mm lens"),
        _v("vitrine", "Principal Vitrine", "FOCAL SPACE", ("vitrine", "display"),
           "frontal view of the principal vitrine, 50 mm lens"),
        _v("seating", "Seating", "SEATING", ("seating", "bench"),
           "three-quarter view of the seating, 35 mm lens", optional=True),
    ),
    "INTERIOR": (
        _v("entry", "Entry", "ARRIVAL / CIRCULATION", ("entry",),
           "eye-level view at the entry, 28 mm lens"),
        _v("main", "Main Space", "FOCAL SPACE", ("main", "hearth", "living"),
           "three-quarter interior view at 1.4 m, 24 mm lens"),
        _v("seating", "Seating", "SEATING", ("seating",),
           "three-quarter view of the seating, 35 mm lens", optional=True),
    ),
}

_GENERIC: tuple[ViewSpec, ...] = (
    _v("approach", "Approach", "ARRIVAL / CIRCULATION", ("approach", "arrival"),
       "distant three-quarter view on approach, 35 mm lens"),
    _v("focal", "Focal Space", "FOCAL SPACE", ("focal", "centre"),
       "frontal hero view, 35 mm lens"),
    _v("occupation", "Occupation", "SEATING", ("seating", "occupation"),
       "three-quarter view of the space in use, 24 mm lens"),
)


class ViewPromptCompiler:
    """Turns one compiled hero prompt into the concept's shot list."""

    def compile_views(
        self, *, hero: ArchitecturalVisualizationPrompt, dna: ConceptDNA,
        concept: StructuredArchitecturalConcept | None, program: DesignProgram,
        brief_text: str = "",
    ) -> list[ArchitecturalVisualizationPrompt]:
        typology = program.typology.value
        specs = VIEW_CATALOGUE.get(typology, _GENERIC)

        identity = [s for s in hero.sections if s.name in IDENTITY_SECTIONS]
        signature = sha256_of("|".join(f"{s.name}:{s.text}" for s in identity))
        named = _named_zones(concept, program)
        subject_base = hero.section("SUBJECT")
        asked = (brief_text or "").lower()

        out: list[ArchitecturalVisualizationPrompt] = []
        for spec in specs:
            area = self._area_text(spec, hero, concept, named)
            if spec.optional and not area and not _asked_for(spec, asked):
                continue          # the concept does not have this area; do not invent it
            out.append(self._one(spec, hero, dna, concept, identity, signature,
                                 subject_base, area))
        return out

    # ---- one view ------------------------------------------------------------
    def _one(self, spec, hero, dna, concept, identity, signature, subject_base,
             area) -> ArchitecturalVisualizationPrompt:
        sections = [PromptSection(
            name="SUBJECT",
            text=f"The {spec.label.lower()} of {_lower_article(subject_base)}",
            source="brief")]
        if area:
            sections.append(PromptSection(name="AREA", text=area, source="concept"))
        sections += list(identity)
        for extra in ("SPATIAL ORGANIZATION", "HUMAN SCALE"):
            text = hero.section(extra)
            if text:
                sections.append(PromptSection(name=extra, text=text, source="concept"))
        camera = spec.camera or hero.section("CAMERA")
        sections.append(PromptSection(name="CAMERA", text=camera, source="compiler"))

        ordered = sorted(sections, key=lambda s: (
            VIEW_SECTION_ORDER.index(s.name) if s.name in VIEW_SECTION_ORDER else 99))
        positive = "\n".join(f"{s.name}: {s.text}" for s in ordered)
        return ArchitecturalVisualizationPrompt(
            prompt_id=deterministic_id("view", dna.concept_id, spec.key, VIEWS_VERSION),
            concept_id=dna.concept_id,
            sections=ordered,
            positive_prompt=positive,
            negative_prompt=hero.negative_prompt,
            camera=camera,
            aspect_ratio=hero.aspect_ratio,
            compiler_version=VIEWS_VERSION,
            prompt_hash=sha256_of(positive),
            inputs_hash=hero.inputs_hash,
            degraded=hero.degraded,
            view_key=spec.key,
            view_label=spec.label,
            shared_signature=signature,
        )

    # ---- where an area's words come from -------------------------------------
    def _area_text(self, spec: ViewSpec, hero, concept, named: dict[str, str]) -> str:
        """Prefer what the model actually wrote about this area, then the hero
        prompt's own section, then nothing — an optional view with nothing to say
        is dropped rather than padded."""
        for alias in (spec.key, *spec.aliases):
            for name, text in named.items():
                if alias in name:
                    return text
        if spec.source_section:
            return hero.section(spec.source_section)
        return ""


def _asked_for(spec: ViewSpec, brief_text: str) -> bool:
    """The brief is the most reliable signal of all.

    'a Sangeeth with a dance floor and a bar' must produce those two views even when
    the model's own zone list never mentions them — the client asked for them, and a
    missing shot is a worse failure than a thin one.
    """
    if not brief_text:
        return False
    terms = (spec.key.replace("_", " "), spec.label.lower(), *spec.aliases)
    return any(t and t in brief_text for t in terms)


def _named_zones(concept: StructuredArchitecturalConcept | None,
                 program: DesignProgram) -> dict[str, str]:
    """Zones the model or the programme actually named, keyed by lowered name."""
    found: dict[str, str] = {}
    for zone in getattr(program, "required_zones", []) or []:
        name = str(getattr(zone, "zone", "")).strip().lower()
        if name:
            found.setdefault(name, "")
    if concept is not None:
        for zone in concept.program.additional_zones or []:
            text = str(zone).strip()
            if not text:
                continue
            # "dance floor: a sunken terrazzo disc" -> key "dance floor"
            head, _, tail = text.partition(":")
            found[head.strip().lower()] = (tail.strip() or text)
        for field, value in (("back of house", concept.program.back_of_house),
                             ("service access", concept.program.service_access)):
            if value:
                found[field] = value
    return {k: v for k, v in found.items() if v}


def _lower_article(subject: str) -> str:
    """'A wedding mandap for 500 people…' -> 'a wedding mandap for 500 people…'"""
    s = (subject or "").strip()
    return (s[0].lower() + s[1:]) if s else s
