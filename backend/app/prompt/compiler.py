"""The prompt compiler.

Deterministic. No model call. A join over the ontology, the genotype, the scene
graph and a versioned template — which is why the output can be hashed, diffed,
replayed and trusted, and why it is the engine's terminal artefact rather than an
intermediate on the way to an image API.
"""
from __future__ import annotations

from app.core.hashing import sha256_of
from app.core.ids import deterministic_id
from app.core.versions import PROMPT_COMPILER_VERSION
from app.domain.antibrief import AntiBrief
from app.domain.brief import DesignProgram
from app.domain.common import ViewRole
from app.domain.concept import ConceptDNA
from app.domain.prompt import PromptCompilation, PromptSegment
from app.domain.scene import SceneGraph
from app.ontology.graph import Ontology
from app.ontology.index import OntologyPrincipleIndex, PrincipleIndex

def _principle_ids(dna: ConceptDNA) -> list[str]:
    """Every principle attached to a concept: the classic single id plus any
    reference-derived ids carried on the reference context."""
    ids: list[str] = []
    if dna.principle_id:
        ids.append(dna.principle_id)
    ctx = getattr(dna, "reference_context", None)
    if ctx is not None:
        ids += [i for i in ctx.injected_principle_ids if i not in ids]
    return ids


GLOBAL_NEGATIVES = [
    "cgi plastic", "oversaturated", "fisheye", "watermark", "text overlay",
    "distorted perspective", "extra limbs",
]
REGISTER_PHRASE = {
    "ARCHITECTURAL_PHOTO": "Photographic architectural visualisation, accurate construction, natural materials",
    "CINEMATIC": "Cinematic architectural still, dramatic contrast, anamorphic feel",
    "DIAGRAMMATIC": "Clean architectural diagram, flat lighting, orthographic clarity",
    "PAINTERLY": "Painterly architectural illustration, visible brushwork",
}
VIEW_DEFAULTS = {
    ViewRole.HERO: ("Three-quarter view from the approach", 1.6, 35.0),
    ViewRole.ARRIVAL: ("Eye-level view on the approach axis at the threshold", 1.6, 28.0),
    ViewRole.OCCUPIED: ("View from the seating toward the focus, occupied", 1.2, 50.0),
    ViewRole.DETAIL: ("Close view of the signature junction", 1.4, 85.0),
    ViewRole.NIGHT: ("Three-quarter view from the approach after dark", 1.6, 35.0),
}


def compile_prompt(
    ont: Ontology,
    dna: ConceptDNA,
    program: DesignProgram,
    scene: SceneGraph | None,
    antibrief: AntiBrief | None = None,
    view_role: ViewRole = ViewRole.HERO,
    dialect: str = "GENERIC",
    seed: int = 0,
    principles: PrincipleIndex | None = None,
) -> PromptCompilation:
    g, p = dna.genotype, dna.phenotype
    L, PH = ont.label, ont.phrase
    lint: list[str] = []
    segs: list[PromptSegment] = []
    degraded = scene is None or scene.status == "FAILED"

    def add(kind: str, text: str, sources: list[str]) -> None:
        if text:
            segs.append(PromptSegment(order=len(segs) + 1, kind=kind, text=text.strip(), sources=sources))

    def phrase(ref: str, source: str) -> str:
        node = ont.nodes.get(ref)
        if node and not node.phrase:
            lint.append(f"missing prompt_phrase for {ref}; fell back to label")
        return PH(ref)

    # 1 SUBJECT
    subject = (f"Architectural visualisation of a "
               f"{program.typology.value.replace('_', ' ').lower()} — \"{p.title}\".")
    add("SUBJECT", subject, ["program.typology", "phenotype.title"])
    # 2 LANGUAGE
    add("LANGUAGE", phrase(g.architectural_language.value, "arch").capitalize() + ".",
        ["genotype.architectural_language"])
    # 3 FORM
    params = ", ".join(f"{pp.name.replace('_', ' ')} {pp.value:g}{pp.unit}" for pp in g.geometry.params)
    add("FORM", f"{phrase(g.geometry.system, 'geo').capitalize()}"
                + (f", {params}." if params else "."), ["genotype.geometry"])
    # 4 SCALE — from the scene graph when available
    if scene and not degraded:
        main = max((n for n in scene.by_type("zone")), key=lambda n: n.area_m2 or 0, default=None)
        el = scene.node("element_signature")
        if main:
            add("SCALE",
                f"A {main.width_m:.1f} x {main.depth_m:.1f} m {main.role} "
                + (f"set {abs(main.level_m):.1f} m below grade, " if main.level_m < -0.05 else "")
                + f"within a {scene.site.width_m:.0f} x {scene.site.depth_m:.0f} m site"
                + (f", the structure rising {el.height_m:.1f} m." if el and el.height_m else "."),
                ["scene.zone", "scene.site", "scene.element_signature.height_m"])
    else:
        add("SCALE", phrase(g.scale_strategy.value, "scale").capitalize() + ".",
            ["genotype.scale_strategy"])
        lint.append("SCALE segment degraded: no scene graph")
    # 5 STRUCTURE
    add("STRUCTURE", f"{phrase(g.structural_logic.value, 'struct').capitalize()}, "
                     f"{phrase(g.tectonic_logic.value, 'tect')}.",
        ["genotype.structural_logic", "genotype.tectonic_logic"])
    # 6 MATERIAL
    mats = sorted(g.material_palette, key=lambda m: -m.share)
    mat_text = (f"{phrase(mats[0].material, 'm0').capitalize()} as the primary surface"
                + (", with " + ", ".join(phrase(m.material, f"m{i}") for i, m in enumerate(mats[1:], 1))
                   if len(mats) > 1 else "") + ".")
    add("MATERIAL", mat_text, [f"genotype.material_palette[{i}]" for i in range(len(mats))])
    # 7 STAGING
    narrative = " then ".join(phrase(s, "nar") for s in g.spatial_narrative)
    add("STAGING", f"The gathering is {phrase(g.occupation_staging.value, 'stage')}; "
                   f"the sequence is {narrative}.",
        ["genotype.occupation_staging", "genotype.spatial_narrative"])
    # 8 OCCUPANCY — from the scene graph
    if scene and not degraded:
        occ = next((n for n in scene.by_type("occupancy")), None)
        if occ:
            add("OCCUPANCY", f"{occ.count} people {occ.posture} in the space.",
                ["scene.occupancy_guests.count"])
    else:
        add("OCCUPANCY", f"{program.capacity.guests} people present.", ["program.capacity.guests"])
    # 9 LIGHTING
    light_text = phrase(g.lighting_philosophy.value, "light").capitalize()
    if scene and not degraded:
        lamp = scene.node("light_primary")
        if lamp and lamp.count:
            light_text += f"; {lamp.count} sources at {lamp.cct_k} K"
    add("LIGHTING", light_text + ".", ["genotype.lighting_philosophy", "scene.light_primary"])
    # 10 ATMOSPHERE
    add("ATMOSPHERE", f"{phrase(g.emotional_register.value, 'emo').capitalize()}. "
                      f"{p.visual_direction.atmosphere.capitalize()}. "
                      f"The space reads as {p.signature_read}.",
        ["genotype.emotional_register", "phenotype.visual_direction.atmosphere",
         "phenotype.signature_read"])
    # 11 CAMERA — from the scene graph camera node when available
    label, height, lens = VIEW_DEFAULTS[view_role]
    cam = scene.camera(view_role.value) if scene and not degraded else None
    if cam:
        height, lens = cam.eye_height_m or height, cam.lens_mm or lens
        add("CAMERA", f"{label}, eye level {height:.1f} m, {lens:g} mm.", ["scene.camera_hero"])
    else:
        add("CAMERA", f"{label}, eye level {height:.1f} m, {lens:g} mm.", ["view_defaults"])
    # 12 CONTEXT
    add("CONTEXT", f"{phrase(g.site_relationship.value, 'site').capitalize()}, on "
                   f"{program.site.ground.lower()} ground"
                   + (f" at night." if view_role == ViewRole.NIGHT else "."),
        ["genotype.site_relationship", "program.site.ground"])
    # 13 REGISTER
    add("REGISTER", REGISTER_PHRASE[p.visual_direction.depiction_register] + ".",
        ["phenotype.visual_direction.depiction_register"])

    positive = " ".join(s.text for s in segs)

    # ---- negative prompt ----
    negatives: list[str] = []
    for ref in g.anti_attributes:
        node = ont.nodes.get(ref)
        if node:
            negatives.append(node.label.lower())
            negatives.extend(node.neg)
    if antibrief:
        occupied = set(g.all_refs())
        negatives.extend(antibrief.surface_tokens_excluding(occupied))
    # Resolve through the index: a runtime (reference-derived) principle is NOT in
    # ont.principles, and the old `in ont.principles` guard dropped its forbidden
    # tokens silently while passing every test.
    index = principles or OntologyPrincipleIndex(ont)
    for pid in _principle_ids(dna):
        p_obj = index.get(pid)
        if p_obj:
            negatives.extend(p_obj.forbidden_surface_tokens)
    negatives.extend(p.visual_direction.avoid_terms)
    for ref in g.all_refs():
        node = ont.nodes.get(ref)
        if node:
            negatives.extend(node.neg)
    negatives.extend(GLOBAL_NEGATIVES)
    seen, ordered = set(), []
    for t in negatives:
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    negative = ", ".join(ordered)

    inputs = {
        "genotype": g.model_dump(mode="json"),
        "scene_digest": scene.digest_parts() if scene else [],
        "visual_direction": p.visual_direction.model_dump(mode="json"),
        "signature_read": p.signature_read,
        "title": p.title,
        "view_role": view_role.value,
        "dialect": dialect,
        "compiler_version": PROMPT_COMPILER_VERSION,
        "ontology_version": ont.version,
    }
    inputs_hash = sha256_of(inputs)
    return PromptCompilation(
        prompt_id=deterministic_id("pc", dna.concept_id, view_role.value, dialect),
        concept_id=dna.concept_id,
        scene_graph_id=scene.scene_graph_id if scene else None,
        view_role=view_role, dialect=dialect,
        positive_prompt=positive, negative_prompt=negative, segments=segs,
        aspect_ratio="3:2", seed=seed, degraded=degraded, lint_warnings=sorted(set(lint)),
        compiler_version=PROMPT_COMPILER_VERSION, ontology_version=ont.version,
        inputs_hash=inputs_hash,
        prompt_hash=sha256_of(positive + "\x00" + negative),
    )
