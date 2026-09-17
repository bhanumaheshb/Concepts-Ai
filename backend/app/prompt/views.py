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
    "SUBJECT", "AREA", "DIMENSIONS", "ARCHITECTURAL CONCEPT", "SITE", "SPATIAL ORGANIZATION",
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
    # ORTHOGRAPHIC drawings are a different KIND of image, not another camera angle:
    # they carry dimensions and must actively suppress perspective, which image models
    # apply by default. `axis` selects which dimensions are annotated.
    orthographic: bool = False
    axis: str = ""                # "plan" | "front" | "side"


def _v(key, label, section="", aliases=(), camera="", optional=False,
       orthographic=False, axis="") -> ViewSpec:
    return ViewSpec(key=key, label=label, source_section=section, aliases=aliases,
                    camera=camera, optional=optional, orthographic=orthographic,
                    axis=axis)


# The canonical shot list per typology. Optional views appear only when the programme
# or the model names them, so a ceremony with no bar does not get an invented one.
# ── the areas every celebration venue has, whatever is happening in it ───────
# Shared so a sangeeth and a wedding in the SAME convention space are photographed
# from the same positions; only the focal element and the optional areas differ.
_ENTRANCE = _v("entrance", "Entrance Facade", "ARRIVAL / CIRCULATION",
               ("entry", "arrival", "gate", "facade", "porte cochere"),
               "eye-level three-quarter view at the threshold, 28 mm lens, looking in")
# key stays "walkway": it is a stable identifier in API responses and in test_views.
_PATHWAY = _v("walkway", "Pathway", "WALKWAY",
              ("aisle", "processional", "path", "walkway", "corridor", "passage"),
              "low eye-level along the processional axis, 35 mm lens, one-point perspective")
_SEATING = _v("seating", "Seating", "SEATING", ("guest seating", "audience", "rounds"),
              "raised three-quarter view across the seating, 24 mm lens")
_SIDE_WALLS = _v("side_walls", "Side Wall Ambience", "ATMOSPHERE",
                 ("side wall", "perimeter", "drape", "ambience", "flank"),
                 "oblique view along one flank wall at 1.6 m, 35 mm lens, grazing light")
_LOUNGE = _v("lounge", "Lounge", "", ("lounge", "sofa", "vip", "seating pod", "chill"),
             "three-quarter view into the lounge at 1.4 m, 35 mm lens", optional=True)
_BAR = _v("bar", "Bar Counter", "", ("bar", "counter", "beverage"),
          "three-quarter view of the bar counter, 50 mm lens, close", optional=True)
_DANCE = _v("dance_floor", "Dance Floor", "", ("dance", "sangeeth", "performance"),
            "wide view across the dance floor at 1.6 m, 24 mm lens, evening light",
            optional=True)
_STAGE = _v("stage", "Performance Stage", "FOCAL SPACE",
            ("stage", "platform", "performance", "riser"),
            "frontal hero view, 35 mm lens, the full stage width in frame")

# ── the FOCAL element, which is what the tradition actually decides ──────────
# A mandap, a nikah stage, an altar and a palki sahib are not interchangeable
# dressings of one object; they differ in axis, enclosure, and what must stay open.
FOCAL_BY_TRADITION: dict[str, ViewSpec] = {
    "HINDU": _v("mandap", "Mandap", "FOCAL SPACE",
                ("mandap", "ceremony", "canopy", "havan", "fire"),
                "frontal hero view, 35 mm lens, the canopy centred and complete in frame, "
                "the fire position visible and open to the sky"),
    "MUSLIM": _v("nikah_stage", "Nikah Stage", "FOCAL SPACE",
                 ("nikah", "ceremony", "stage", "sofa", "majlis"),
                 "frontal hero view, 35 mm lens, the seated ceremonial platform centred, "
                 "no fire element, screening and approach legible"),
    "CHRISTIAN": _v("altar", "Altar", "FOCAL SPACE",
                    ("altar", "ceremony", "chancel", "arch"),
                    "frontal view down the nave axis, 35 mm lens, the altar terminating "
                    "a long axial approach"),
    "SIKH": _v("palki", "Palki Sahib", "FOCAL SPACE",
               ("palki", "ceremony", "canopy", "darbar"),
               "frontal hero view, 35 mm lens, the canopy centred above the dais, "
               "floor seating in the foreground"),
}
_FOCAL_DEFAULT = _v("focal", "Ceremony Focus", "FOCAL SPACE",
                    ("ceremony", "focal", "centre", "stage", "canopy"),
                    "frontal hero view, 35 mm lens, the ceremonial focus centred")

# ── shot list per EVENT, focal slot filled by tradition ──────────────────────
# A sangeeth has a performance stage and no ceremonial focus; a wedding has a
# ceremonial focus and no bar unless the brief asks for one.
EVENT_CATALOGUE: dict[str, tuple[ViewSpec, ...]] = {
    "SANGEETH": (_ENTRANCE, _PATHWAY, _STAGE, _SEATING, _DANCE, _LOUNGE, _BAR,
                 _SIDE_WALLS),
    "RECEPTION": (_ENTRANCE, _PATHWAY, _STAGE, _SEATING, _LOUNGE, _BAR, _SIDE_WALLS),
    "MEHENDI": (_ENTRANCE, _PATHWAY, _SEATING, _LOUNGE, _SIDE_WALLS),
    "HALDI": (_ENTRANCE, _PATHWAY, _SEATING, _LOUNGE, _SIDE_WALLS),
}


def event_views(event_type: str, tradition: str) -> tuple[ViewSpec, ...] | None:
    """Shot list for an event whose focal element the tradition decides.

    Returns None when the event is not one of the celebration types, so the caller
    falls back to the typology catalogue and nothing existing changes behaviour.
    """
    if event_type in EVENT_CATALOGUE:
        return EVENT_CATALOGUE[event_type]
    if event_type in ("WEDDING", "ENGAGEMENT"):
        focal = FOCAL_BY_TRADITION.get(tradition, _FOCAL_DEFAULT)
        return (_ENTRANCE, _PATHWAY, focal, _SEATING, _LOUNGE, _BAR, _SIDE_WALLS)
    return None


VIEW_CATALOGUE: dict[str, tuple[ViewSpec, ...]] = {
    "WEDDING_MANDAP": (
        _ENTRANCE, _PATHWAY,
        _v("mandap", "Mandap", "FOCAL SPACE", ("ceremony", "canopy", "stage"),
           "frontal hero view, 35 mm lens, the canopy centred and complete in frame"),
        _SEATING, _DANCE, _BAR,
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

# ── measured drawings, appended to EVERY shot list ───────────────────────────
# A render shows what a space feels like; a drawing shows what it IS. These carry
# the scene graph's real dimensions, so the model annotates numbers it was given
# rather than inventing plausible ones.
DRAWING_VIEWS: tuple[ViewSpec, ...] = (
    _v("plan", "Plan", orthographic=True, axis="plan", camera=(
        "orthographic top-down plan drawing, true orthographic projection, "
        "camera axis vertical, no perspective convergence and no vanishing point, "
        "flat even illumination, dimension lines and arrows, measured architectural "
        "drawing rather than a render")),
    _v("front_elevation", "Front Elevation", orthographic=True, axis="front", camera=(
        "orthographic front elevation, camera axis perpendicular to the principal "
        "face, no perspective convergence and no foreshortening, flat frontal "
        "illumination, dimension lines and arrows, measured architectural drawing")),
    _v("side_elevation", "Side Elevation", orthographic=True, axis="side", camera=(
        "orthographic side elevation from the left, camera axis perpendicular to the "
        "flank, no perspective convergence and no foreshortening, flat illumination, "
        "dimension lines and arrows, measured architectural drawing")),
)

# Suppressing perspective is the whole difficulty: image models apply it by default,
# and the word "elevation" alone does not stop them.
ORTHO_NEGATIVES = (
    "perspective", "vanishing point", "foreshortening", "depth of field",
    "three-quarter view", "camera tilt", "wide angle distortion", "bokeh",
)


def _dimension_text(axis: str, scene, program) -> str:
    """The numbers annotated on a drawing. Taken from the solved scene where one
    exists, and from the programme's site otherwise — never left to the model."""
    w = d = h = None
    if scene is not None and getattr(scene, "site", None) is not None:
        w, d = scene.site.width_m, scene.site.depth_m
        heights = [n.height_m for n in getattr(scene, "nodes", []) if n.height_m]
        h = max(heights) if heights else None
    if w is None:
        w, d = program.site.width_m, program.site.depth_m
    h = h or program.site.height_clear_m

    def m(v):
        return f"{v:.1f} m ({v * 3.28084:.0f} ft)"

    if axis == "plan":
        return (f"Overall width {m(w)} annotated across the top, overall depth {m(d)} "
                f"annotated down the side.")
    if axis == "front":
        return (f"Overall width {m(w)} annotated across the base"
                + (f", overall height {m(h)} annotated at the side." if h else "."))
    return (f"Overall depth {m(d)} annotated across the base"
            + (f", overall height {m(h)} annotated at the side." if h else "."))


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
        brief_text: str = "", scene=None,
    ) -> list[ArchitecturalVisualizationPrompt]:
        # The event and its tradition decide the shot list when they are known; a
        # brief that names neither falls back to the typology catalogue unchanged.
        specs = event_views(
            getattr(program, "event_type", None) and program.event_type.value or "",
            getattr(program, "tradition", None) and program.tradition.value or "",
        ) or VIEW_CATALOGUE.get(program.typology.value, _GENERIC)

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

        # ── state pairs ──────────────────────────────────────────────────────
        # When the concept transforms, the focal view is rendered once per state
        # from the IDENTICAL camera. Holding the camera still is the entire point:
        # it is what proves the second image is the same room, not another design.
        states = list(getattr(concept, "stage_states", None) or [])
        if len(states) > 1 and out:
            focal = next((p for p in out if p.view_key in
                          ("stage", "mandap", "nikah_stage", "altar", "palki", "focal")),
                         out[0])
            for st in states:
                out.append(self._state_view(focal, dna, st, signature))

        # The measured drawings close every set. They share the identity sections, so
        # a plan and a hero render describe demonstrably the same building.
        for spec in DRAWING_VIEWS:
            out.append(self._one(spec, hero, dna, concept, identity, signature,
                                 subject_base, _dimension_text(spec.axis, scene, program)))
        return out

    # ---- one state of an existing view ---------------------------------------
    def _state_view(self, base, dna, state, signature) -> ArchitecturalVisualizationPrompt:
        """`base` verbatim, with a STATE section inserted and the camera untouched."""
        bits = [b for b in (state.condition, state.lighting, state.palette) if b]
        if state.changed_from_previous:
            bits.append(f"Changed from the previous state: {state.changed_from_previous}")
        sections = list(base.sections)
        insert_at = next((i for i, s in enumerate(sections)
                          if s.name not in ("SUBJECT", "AREA", "DIMENSIONS")), 1)
        sections.insert(insert_at, PromptSection(
            name="STATE", text=" ".join(bits), source="concept"))
        positive = "\n".join(f"{s.name}: {s.text}" for s in sections)
        key = f"{base.view_key}__{state.key}"
        return ArchitecturalVisualizationPrompt(
            prompt_id=deterministic_id("view", dna.concept_id, key, VIEWS_VERSION),
            concept_id=dna.concept_id,
            sections=sections,
            positive_prompt=positive,
            negative_prompt=base.negative_prompt,
            camera=base.camera,               # identical, deliberately
            aspect_ratio=base.aspect_ratio,
            compiler_version=VIEWS_VERSION,
            prompt_hash=sha256_of(positive),
            inputs_hash=base.inputs_hash,
            degraded=base.degraded,
            view_key=key,
            view_label=f"{base.view_label} — {state.label or state.key}",
            shared_signature=signature,
        )

    # ---- one view ------------------------------------------------------------
    def _one(self, spec, hero, dna, concept, identity, signature, subject_base,
             area) -> ArchitecturalVisualizationPrompt:
        sections = [PromptSection(
            name="SUBJECT",
            text=f"The {spec.label.lower()} of {_lower_article(subject_base)}",
            source="brief")]
        if area:
            sections.append(PromptSection(
                # A drawing's "area" text is its dimension annotation, and it comes
                # from the solved scene rather than from the model.
                name="DIMENSIONS" if spec.orthographic else "AREA",
                text=area, source="compiler" if spec.orthographic else "concept"))
        sections += list(identity)
        # HUMAN SCALE puts figures in the frame, which is wrong in a measured drawing.
        extras = ("SPATIAL ORGANIZATION",) if spec.orthographic \
            else ("SPATIAL ORGANIZATION", "HUMAN SCALE")
        for extra in extras:
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
            negative_prompt=(", ".join([hero.negative_prompt, *ORTHO_NEGATIVES])
                             if spec.orthographic else hero.negative_prompt),
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
