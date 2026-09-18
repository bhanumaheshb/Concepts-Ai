"""One physical description per concept, shared by every image of it.

The Concept tab and the 3D handoff used to describe a concept independently: the
hero prompt from its own sections, the handoff from a different selection of the
same fields. Given two descriptions, an image model draws two buildings — a
Chettinad colonnade in one tab and a white space-frame canopy in the other.

The lock is built once from the concept and its DNA, holds only what can be
built and photographed, and is copied verbatim into every view of both tabs.
Only the camera, the deliverable and the occupancy may differ between views.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.hashing import sha256_of

# Order is the order the sections are written in every prompt.
LOCK_SECTIONS = (
    "ARCHITECTURAL CONCEPT", "STRUCTURE", "GEOMETRY", "MASSING", "MATERIALS",
    "MATERIAL BEHAVIOUR", "PALETTE", "LIGHTING", "LANDSCAPE", "CONSTRUCTION REALISM",
)

_PEOPLE = re.compile(r"\b(people|humans?|guests?|crowds?|performers?|bride|groom|visitors?|"
                     r"dancers?|couple|attendees?|figures?|witnesses)\b", re.I)
# The purpose tail of a sentence ("... to create a sense of intimacy") says what the
# designer hoped to feel. An image model renders it as glow and haze, so it is cut
# and the physical head of the sentence kept.
_PURPOSE_TAIL = re.compile(
    r",?\s*\b(to (create|evoke|convey|suggest|express|emphasi[sz]e|evoke|symboli[sz]e|celebrate|honou?r)|"
    r"(creating|evoking|conveying|suggesting|symboli[sz]ing|embodying|celebrating|reflecting|"
    r"emphasi[sz]ing|honou?ring)\b|"
    r"(that|which) (evokes?|creates?|conveys?|suggests?|symboli[sz]es?|embod(y|ies)|"
    r"celebrates?|reflects?|emphasi[sz]es?)).*$", re.I)
# A clause still carrying these after the tail is cut is interpretation, not description.
_ABSTRACT = re.compile(
    r"\b(manifestation|sense of|feeling of|spirit of|essence|soul|timeless|harmon(y|ious)|"
    r"journey|dialogue|metaphor\w*|poetic|emotion\w*|transcend\w*|narrative|storytelling|"
    r"with a focus on|inspired by the idea)\b", re.I)
# Superlatives and uncountable multitudes are what push a render into the
# over-decorated AI look: hundreds of lamps, endless gold, every surface glowing.
_HYPERBOLE = [
    (re.compile(r"\b(hundreds|thousands) of\b", re.I), "several dozen"),
    (re.compile(r"\b(countless|myriad|endless|innumerable)\b", re.I), "many"),
    (re.compile(r"\b(breathtaking|stunning|majestic|opulent|luxurious|magnificent|"
                r"awe-inspiring|mesmeri[sz]ing|magical|ethereal|dreamlike|grand)\s+", re.I), ""),
]


def physical(text: str) -> str:
    """Only what can be built and photographed: no people, no intentions, no hype."""
    kept: list[str] = []
    for clause in re.split(r"(?<=[.!?;])\s+|;\s*", text or ""):
        clause = _PURPOSE_TAIL.sub("", clause.strip()).strip(" ,;")
        if not clause or _PEOPLE.search(clause) or _ABSTRACT.search(clause):
            continue
        for pattern, repl in _HYPERBOLE:
            clause = pattern.sub(repl, clause)
        clause = " ".join(clause.split())
        if clause and _norm(clause) not in {_norm(k) for k in kept}:
            kept.append(clause)
    return "; ".join(k.rstrip(".;") for k in kept)


def _norm(clause: str) -> str:
    """Comparison key for repeated clauses: "A granite plinth" repeats "Granite plinth"."""
    return re.sub(r"^(a|an|the)\s+", "", clause.lower().rstrip(". "))


@dataclass(frozen=True)
class DesignLock:
    sections: tuple[tuple[str, str, str], ...]     # (name, text, source)

    @property
    def text(self) -> str:
        return "\n".join(f"{n}: {t}" for n, t, _ in self.sections)

    @property
    def signature(self) -> str:
        return signature_of((n, t) for n, t, _ in self.sections)

    def section(self, name: str) -> str:
        return next((t for n, t, _ in self.sections if n == name), "")


def signature_of(pairs) -> str:
    """Hash of the lock sections among `pairs` of (name, text). Views and the handoff
    compute it the same way, so equal signatures mean an identical description."""
    got = {n: t for n, t in pairs if n in LOCK_SECTIONS}
    return sha256_of("|".join(f"{n}:{got[n]}" for n in LOCK_SECTIONS if n in got))


def build_design_lock(ont, dna, concept, program=None) -> DesignLock:
    from app.prompt import architectural as A

    def label(ref: str) -> str:
        node = ont.nodes.get(ref)
        return node.label.lower() if node else ref.split(":")[-1].replace("_", " ")

    g, c = dna.genotype, concept
    geo_refs = g.geometry.system if isinstance(g.geometry.system, list) else [g.geometry.system]
    geo = ", ".join(label(r) for r in geo_refs)
    primary = next(m for m in g.material_palette if m.role.value == "PRIMARY")
    prim = label(primary.material)
    others = [label(m.material) for m in g.material_palette if m.material != primary.material]
    dna_mats = f"{prim} as the primary material" + (
        f", with {', '.join(others)} in secondary roles" if others else "")

    def join(*parts) -> str:
        return "; ".join(p for p in parts if p)

    candidates = {
        "ARCHITECTURAL CONCEPT": (
            join(c.architectural_language, c.concept_thesis) if c else "",
            f"{label(g.architectural_language.value)} expressed through "
            f"{label(g.structural_logic.value)}"),
        "STRUCTURE": (
            join(c.structure.structural_system, c.structure.spans_and_supports,
                 c.structure.module) if c else "",
            f"{label(g.structural_logic.value)}, built as {label(g.tectonic_logic.value)}"),
        "GEOMETRY": (c.structure.geometry if c else "", geo),
        "MASSING": (c.structure.mass_and_void if c else "",
                    f"massing at {label(g.scale_strategy.value)}"),
        "MATERIALS": (
            join(c.materials.primary, ", ".join(c.materials.secondary)) if c else "", dna_mats),
        "MATERIAL BEHAVIOUR": (
            join(c.materials.material_behaviour, c.materials.surface_treatment) if c else "",
            f"{prim} left legible as itself, its texture read by raking light"),
        "PALETTE": ("", _palette(A, g, label, prim)),
        "LIGHTING": (
            join(", ".join(c.lighting.lighting_sources), c.lighting.colour_temperature,
                 c.lighting.height_and_distribution, c.lighting.shadow_behaviour) if c else "",
            label(g.lighting_philosophy.value)),
        "LANDSCAPE": (c.landscape if c else "", "planting kept low so the plan stays readable"),
        "CONSTRUCTION REALISM": (
            c.construction_character if c else "",
            f"assembled as {label(g.tectonic_logic.value)} with a believable load path"),
    }

    profile = getattr(getattr(program, "semantic", None), "profile", None)
    leaks = None
    if profile is not None:
        from app.semantics.knowledge import load_knowledge
        from app.semantics.leakage import find_leaks
        k = load_knowledge()
        leaks = lambda text, where: find_leaks(k, profile, text, where)  # noqa: E731

    out = []
    for name in LOCK_SECTIONS:
        concept_text, dna_text = candidates[name]
        text, source = physical(concept_text), "concept"
        # A model-written section naming an element this event forbids is replaced
        # by the DNA's reading, exactly as the hero compiler did before the lock.
        if text and leaks is not None and leaks(text, name):
            text = ""
        if not text:
            text, source = physical(dna_text) or " ".join(dna_text.split()), "dna"
        if text:
            out.append((name, text, source))
    return DesignLock(tuple(out))


def _palette(A, g, label, prim) -> str:
    colours = []
    for m in g.material_palette[:3]:
        colour = A.COLOUR_BY_MATERIAL.get(m.material.split(":")[-1])
        if colour and colour not in colours:
            colours.append(colour)
    light = A.PALETTE_BY_LIGHTING.get(label(g.lighting_philosophy.value), "")
    palette = "; ".join(colours)
    if light:
        palette = f"{palette} — lit as {light}" if palette else light
    return palette or f"colour led by {prim}"
