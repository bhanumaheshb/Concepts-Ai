"""Building the synthesis request — provider-independent by design.

This is the system's architectural knowledge, not any vendor's. Workers AI, Anthropic and
OpenAI adapters all send exactly these blocks; only the transport differs. Nothing in
this module knows how the model is served.

The governing idea: the model is told what the concept IS and asked to express it as
architecture. Every locked value is restated as an instruction it must satisfy, and the
geometry vocabulary is translated into architectural moves (§9) so the model interprets
rather than parrots the DNA word.
"""
from __future__ import annotations

from app.domain.brief import DesignBrief, DesignProgram
from app.domain.genotype import ConceptGenotype
from app.domain.synthesis import ConstraintEnvelope, LockedFacet
from app.ontology.graph import Ontology

PROMPT_VERSION = "2.0.0"

SYSTEM = """You are an architect and spatial designer producing a concept for an \
architectural visualisation. You think in site, programme, massing, circulation, \
structure, material behaviour and light — not in adjectives.

THE CONCEPT HAS ALREADY BEEN DECIDED. It is given to you as a design vector below.
Your job is to EXPRESS it as architecture, not to choose a different one.

Absolute rules:
1. You may NOT change any locked value. If the structure is "corbelled", you describe a
   corbelled structure; you do not substitute a cable-stayed one.
2. You may NOT change any hard constraint: capacity, dimensions, heights, typology.
3. You interpret geometry architecturally. "radial" becomes radial structural bays and
   centrifugal circulation — not the word "radial" repeated.
4. Structure must be buildable. State spans, supports, the repeated module and how it is
   assembled. If the concept is not physically plausible, say so in
   construction_character; never pretend it is buildable.
5. Materials are described as behaviour, location and interaction with light — never as
   a shopping list.
6. Lighting is described as source, colour temperature, height, distribution and shadow
   behaviour — never as "beautiful warm lighting".
7. Resolve only the programme the brief requires. Do not invent a backstage for a \
restaurant or a mandap for a retail interior.
8. Write for a client presentation: specific, confident, architectural. No marketing \
adjectives, no hedging, no alternatives.

Return ONLY a JSON object matching the requested schema. No prose outside the JSON."""

# §9 — abstract geometry becomes architectural moves. The model is given the
# translation so it interprets rather than repeats.
GEOMETRY_READINGS: dict[str, str] = {
    "radial": "radial structural bays, circular gathering, centrifugal circulation",
    "concentric": "nested rings, a centre that is approached rather than entered",
    "layered": "terraced massing, overlapping thresholds, stacked roof planes",
    "stratified": "terraced massing, overlapping thresholds, stacked roof planes",
    "continuous": "an uninterrupted surface, a folded structural envelope, "
                  "a continuous circulation edge",
    "undulating": "a continuously curving surface whose section changes as you move",
    "fragmented": "separated architectural volumes, controlled gaps, "
                  "a discontinuous roofscape",
    "shard": "separated architectural volumes, controlled gaps, sharp residual space",
    "organic": "non-linear circulation, branching geometry, irregular structural rhythm",
    "orthogonal": "a disciplined grid, aligned bays, clear structural repetition",
    "grid": "a disciplined grid, aligned bays, clear structural repetition",
    "modular": "one repeated unit at several scales, legible joints, additive assembly",
    "spiral": "a route that gains height as it turns, a continuously revealed centre",
    "nested": "volumes inside volumes, thresholds crossed one after another",
    "cellular": "an aggregate of small rooms, shared walls, a dense plan",
    "vaulted": "repeated spanning arches, load carried to discrete points",
    "cantilever": "mass held out beyond its support, a visible counterweight",
    "monolithic": "one apparently continuous mass, few visible joints, carved openings",
}


def geometry_reading(refs: list[str]) -> list[str]:
    out: list[str] = []
    for ref in refs:
        token = ref.split(":")[-1].lower()
        for key, reading in GEOMETRY_READINGS.items():
            if key in token and reading not in out:
                out.append(reading)
    return out


def build_constraints(ont: Ontology, program: DesignProgram, brief: DesignBrief,
                      genotype: ConceptGenotype,
                      forbidden_tokens: list[str] | None = None) -> ConstraintEnvelope:
    """Split the world into what may not move, what is guidance, and what is open (§17)."""
    locked: list[LockedFacet] = []

    def add(facet: str, ref: str) -> None:
        node = ont.nodes.get(ref)
        locked.append(LockedFacet(
            facet=facet, ref=ref,
            label=node.label if node else ref.split(":")[-1].replace("_", " "),
            description=(node.desc or "") if node else ""))

    add("architectural_language", genotype.architectural_language.value)
    for ref in genotype.geometry.system if isinstance(genotype.geometry.system, list) \
            else [genotype.geometry.system]:
        add("geometry", ref)
    add("structural_logic", genotype.structural_logic.value)
    add("tectonic_logic", genotype.tectonic_logic.value)
    add("lighting_philosophy", genotype.lighting_philosophy.value)
    add("emotional_register", genotype.emotional_register.value)
    add("site_relationship", genotype.site_relationship.value)
    add("occupation_staging", genotype.occupation_staging.value)
    add("scale_strategy", genotype.scale_strategy.value)
    for ref in genotype.spatial_narrative:
        add("spatial_narrative", ref)
    for m in genotype.material_palette:
        add(f"material:{m.role.value.lower()}", m.material)

    hard: list[str] = [
        f"The concept is a {program.typology.value.replace('_', ' ').lower()}.",
    ]
    if program.capacity and program.capacity.guests:
        hard.append(f"Capacity is exactly {program.capacity.guests} people — "
                    f"do not change this number.")
    site = program.site
    dims = ""
    if getattr(site, "width_m", None) and getattr(site, "depth_m", None):
        dims = f"{site.width_m}m x {site.depth_m}m"
        hard.append(f"The site is {dims}. Do not change these dimensions.")
    max_h = getattr(site, "max_height_m", None)
    if max_h:
        hard.append(f"Maximum height is {max_h}m. Do not exceed it.")
    for c in program.invariants:
        hard.append(c.statement if hasattr(c, "statement") else str(c))
    hard.append("Every locked design value listed below must be expressed, not replaced.")

    soft = [s.statement if hasattr(s, "statement") else str(s)
            for s in program.soft_intents]
    creative = [
        "the specific architectural form that expresses the locked values",
        "the spatial sequence and how a person experiences it",
        "structural module, spans and assembly detail",
        "surface treatment and how material meets light",
        "the camera that best communicates the architecture",
    ]

    return ConstraintEnvelope(
        hard=hard, soft=soft, creative=creative, locked_facets=locked,
        forbidden_tokens=sorted(set(forbidden_tokens or [])),
        capacity=program.capacity.guests if program.capacity else None,
        site_dimensions=dims,
        max_height_m=max_h,
        typology=program.typology.value,
    )


def build_user_prompt(brief: DesignBrief, program: DesignProgram,
                      constraints: ConstraintEnvelope, genotype: ConceptGenotype,
                      reference_statements: list[str] | None = None,
                      trend_statements: list[str] | None = None,
                      repair_instruction: str = "") -> str:
    lines: list[str] = []
    a = lines.append

    a("## BRIEF")
    a(brief.raw_text.strip())
    if brief.location:
        a(f"Location: {brief.location}")
    a("")

    a("## HARD CONSTRAINTS — you may not alter any of these")
    for h in constraints.hard:
        a(f"- {h}")
    a("")

    if constraints.soft:
        a("## SOFT INTENT — guidance you may interpret")
        for s in constraints.soft:
            a(f"- {s}")
        a("")

    a("## CONCEPT DNA — the design decision, already made. Express it.")
    by_facet: dict[str, list[LockedFacet]] = {}
    for lf in constraints.locked_facets:
        by_facet.setdefault(lf.facet, []).append(lf)
    for facet, items in by_facet.items():
        label = ", ".join(i.label for i in items)
        desc = next((i.description for i in items if i.description), "")
        a(f"- {facet.replace('_', ' ').upper()}: {label}"
          + (f" — {desc}" if desc else ""))
    a("")

    readings = geometry_reading([lf.ref for lf in constraints.locked_facets
                                 if lf.facet == "geometry"])
    if readings:
        a("## HOW TO READ THE GEOMETRY ARCHITECTURALLY")
        for r in readings:
            a(f"- {r}")
        a("(Interpret it. Do not simply repeat the word.)")
        a("")

    if reference_statements:
        a("## TRANSFERRED PRINCIPLES — express these as architecture.")
        a("Do NOT name or depict their source; the source is not part of the concept.")
        for s in reference_statements:
            a(f"- {s}")
        a("")
    if trend_statements:
        a("## CURRENT DESIGN READINGS")
        for s in trend_statements:
            a(f"- {s}")
        a("")

    a("## PROGRAMME TO RESOLVE")
    zones = [z.name if hasattr(z, "name") else str(z) for z in program.required_zones]
    if zones:
        for z in zones:
            a(f"- {z}")
    else:
        a("- derive the programme from the brief; do not invent zones it does not need")
    a("")

    if constraints.forbidden_tokens:
        a("## FORBIDDEN WORDS — must not appear anywhere in your output")
        a(", ".join(constraints.forbidden_tokens[:60]))
        a("")

    if repair_instruction:
        a("## YOUR PREVIOUS ANSWER WAS REJECTED. Fix exactly these problems:")
        a(repair_instruction)
        a("Keep everything else. Return the corrected JSON object.")
        a("")

    a("## TASK")
    a("Express this concept as a buildable piece of architecture. Resolve the "
      "programme, the structure and the light. Return the JSON object only.")
    return "\n".join(lines)
