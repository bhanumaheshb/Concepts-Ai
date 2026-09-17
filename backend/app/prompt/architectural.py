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
    "GEOMETRY", "MASSING", "MATERIALS", "MATERIAL BEHAVIOUR", "LIGHTING", "PALETTE",
    "LANDSCAPE",
    "ATMOSPHERE", "HUMAN SCALE", "CAMERA", "ARCHITECTURAL VISUALIZATION STYLE",
    "CONSTRUCTION REALISM",
]

STYLE = ("architectural visualisation, physically based rendering, accurate daylight "
         "and artificial light balance, correct perspective, believable construction "
         "detail, no illustration styling")

# A single fixed style string made every concept render in one photographic idiom,
# so ten genuinely different buildings came back as ten variations of the same
# civic stone hall. The register follows the concept's OWN emotional_register and
# lighting_philosophy — a scenographic concept and a vernacular one should not be
# photographed the same way.
STYLE_BY_REGISTER: dict[str, str] = {
    # keys are the ontology's own emotional_register labels — all twelve, so no
    # concept silently falls back to the neutral architectural idiom
    "euphoric":      "celebratory event photography, saturated colour, crowd mid-celebration",
    "playful":       "lively event photography, colour-rich, movement visible in the frame",
    "ceremonial":    "formal ceremonial photography, composed symmetry, deep saturated colour",
    "theatrical":    "stage photography, dramatic directional light, strong colour contrast",
    "reverent":      "quiet ceremonial photography, warm restrained colour, still figures",
    "tender":        "soft intimate photography, gentle warm light, close human scale",
    "intimate":      "close intimate photography, shallow depth, warm low-level light",
    "contemplative": "calm architectural photography, soft even light, restrained palette",
    "sublime":       "wide dramatic photography, vast scale, atmospheric depth",
    "melancholic":   "muted photography, desaturated palette, overcast diffuse light",
    "austere":       "spare architectural photography, hard light, minimal colour",
    "unsettling":    "cinematic photography, high contrast, deep shadow, cold accents",
}

# Colour is the single biggest thing missing from a purely architectural prompt: an
# image model given no palette defaults to neutral stone. Each lighting philosophy
# implies a colour world, stated explicitly so the render has one.
PALETTE_BY_LIGHTING: dict[str, str] = {
    "diya field":          "deep amber and ochre against near-black, hundreds of small flame points",
    "candle scatter":      "warm amber pools against dark ground",
    "oil-lamp field":      "amber and umber, flame-lit, darkness between the lights",
    "open flame":          "orange and deep red, firelight falling on faces",
    "chandelier cluster":  "warm gold and crystal white against a darker field",
    "string canopy":       "warm honey overhead, deep blue-black sky beyond",
    "pin-spot floral":     "saturated flower colour picked out of darkness, black between",
    "uplit canopy":        "the structure glowing warm from beneath, cool sky above",
    "emissive surface":    "cool white and cyan light emitted by the surfaces themselves",
    "projected light":     "shifting projected colour across a neutral ground",
    "grazing wash":        "warm sand and cream, low raking light, long shadows",
    "silhouette backlight": "figures dark against a bright saturated field",
    "darkness and pools":  "near-black with isolated warm pools of light",
    "filtered daylight":   "soft daylight broken into pattern, cool shadow, warm sunlight",
    "direct sun shafts":   "hard white sun shafts against deep shade",
    "skylight well":       "one bright overhead source, walls falling to shadow",
    "reflected daylight":  "soft bounced daylight, low contrast, pale tones",
}


# What each material actually LOOKS like. The palette was previously keyed to
# lighting alone, so two concepts sharing a light source got the same colour world
# however different their materials — corten steel and PTFE membrane both came back
# as "warm amber". Colour is a property of the material; light only modifies it.
COLOUR_BY_MATERIAL: dict[str, str] = {
    # stone + earth
    "marble": "cool white with grey veining",
    "limestone": "pale bone and cream",
    "sandstone": "warm pink-ochre",
    "granite": "flecked grey-black",
    "dry_stack_stone": "dry grey and buff, shadowed joints",
    "rammed_earth": "banded ochre, umber and sand",
    "terracotta": "burnt orange-red",
    "brick": "deep red-brown, mortar grey",
    "lime_plaster": "chalk white, faintly warm",
    "jaali_screen": "pale stone, pierced, shadow-patterned",
    # metal
    "brass": "warm yellow metal, darkening at the edges",
    "brass_repousse": "hammered gold-brown with dark relief",
    "corten_steel": "oxidised rust orange-brown",
    "polished_steel": "cold mirror silver",
    "anodised_aluminium": "matte grey with a coloured sheen",
    "kundan_inlay": "jewel green, ruby and gold points",
    "mirror_mosaic": "fractured silver, throwing coloured light",
    "mirror_polymer": "liquid silver, distorted reflection",
    # wood
    "teak": "deep honey brown",
    "laminated_timber": "pale blond timber, visible lamination",
    "mango_wood": "mid golden brown, open grain",
    "charred_wood": "matte black, cracked, silver-edged",
    "bamboo": "green-gold culms, pale nodes",
    # textile
    "silk_drape": "lustrous, catching light along the fold",
    "zari_brocade": "deep colour shot through with metallic thread",
    "khadi_cotton": "undyed oatmeal and ecru",
    "woven_jute": "coarse straw brown",
    "canvas_membrane": "off-white, warm where light passes through",
    "ptfe_membrane": "translucent white, glowing when lit",
    # glass + light + water
    "clear_glass": "colourless, taking colour from behind it",
    "fritted_glass": "milky white, softening whatever is beyond",
    "emissive_light": "the surface itself is the light source",
    "still_water": "black mirror holding the sky",
    "moving_water": "broken silver and white",
    # plant
    "living_plant": "deep green, many tones",
    "foliage_canopy": "layered green, light filtering through",
    "cut_flower": "massed saturated colour",
    "marigold_mass": "dense saturated orange and gold",
    "fresh_flower_wall": "packed blooms, one dominant hue",
    "banana_stem": "pale green-white, wet-cut",
}

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

        # PALETTE is composed, not looked up: the concept's own materials give the
        # colour, its lighting philosophy gives the light that falls on them. Two
        # concepts can now only share a palette if they share both.
        lighting_label = self._label(g.lighting_philosophy.value)
        mat_colours = []
        for m in g.material_palette[:3]:
            key = m.material.split(":")[-1]
            c_txt = COLOUR_BY_MATERIAL.get(key)
            if c_txt and c_txt not in mat_colours:
                mat_colours.append(c_txt)
        light_txt = PALETTE_BY_LIGHTING.get(lighting_label, "")
        palette = "; ".join(mat_colours)
        if light_txt:
            palette = f"{palette} — lit as {light_txt}" if palette else light_txt
        add("PALETTE", palette or f"colour led by {prim}", "dna")

        register = self._label(g.emotional_register.value)
        add("ARCHITECTURAL VISUALIZATION STYLE",
            f"{STYLE_BY_REGISTER.get(register, STYLE)}, correct perspective, "
            "believable construction detail", "dna")
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

        palette_text = next((x.text for x in sections if x.name == "PALETTE"), "")
        negatives = self._negatives(constraints, concept, extra_negatives,
                                    self._affirmed_words(dna, concept, palette_text))
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
                   extra: list[str] | None,
                   affirmed: set[str] | None = None) -> list[str]:
        """Concept DNA + anti-brief + reference lexicon + the concept's own (§16).

        NEVER NEGATE WHAT THE CONCEPT AFFIRMED. The anti-brief's surface tokens exist
        to steer FACET SELECTION away from the obvious answer; carried unfiltered into
        an image prompt they mean something else entirely — they delete the subject's
        own vocabulary. A wedding whose palette genuinely contains massed marigold was
        being rendered with "marigold" in its negative prompt, so the engine
        contradicted its own decision and every concept came back as bare stone.

        A cliché is a whole configuration, not a word. If this concept chose the
        material, the word describes what it IS and cannot also describe what it must
        avoid.
        """
        affirmed = affirmed or set()
        out: list[str] = []
        out += [t.lower() for t in constraints.forbidden_tokens]
        out += [t.lower() for t in (extra or [])]
        if concept:
            out += [a.lower().removeprefix("no ").strip() for a in concept.anti_cliches]
        out += GLOBAL_NEGATIVES
        seen, ordered = set(), []
        for t in out:
            t = " ".join(t.split())
            if not t or t in seen:
                continue
            # drop a negative that names something this concept actually uses
            if any(w in affirmed for w in t.split()):
                continue
            seen.add(t)
            ordered.append(t)
        return ordered

    def _affirmed_words(self, dna, concept, palette: str = "") -> set[str]:
        """Every word the concept's own materials, lighting and tectonic name.

        Taken from the SOLVED genotype rather than from prose, so it is exactly the
        set of decisions the engine committed to.
        """
        words: set[str] = set()
        g = dna.genotype

        def eat(label: str) -> None:
            words.update(w for w in label.lower().replace("-", " ").split() if len(w) > 2)

        for m in g.material_palette:
            eat(self._label(m.material))
        for facet in ("lighting_philosophy", "tectonic_logic", "architectural_language",
                      "geometry_system", "occupation_staging"):
            v = g.facet_value(facet)
            if v:
                eat(self._label(v))
        if concept is not None:
            eat(getattr(concept.materials, "primary", "") or "")
        # The PALETTE section is an affirmation too: a prompt that says "warm gold"
        # and then bans "gold" is arguing with itself in the same breath.
        eat(palette)
        return words
