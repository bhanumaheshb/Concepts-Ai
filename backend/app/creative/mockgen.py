"""Deterministic mock generators.

The phenotype generator is the important one: it converts a solved genotype into
readable prose using the ontology's own node descriptions, so ten different
genotypes produce ten visibly different concepts. The differences originate in the
engine, not here.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.core.seeded import SeededRandom
from app.creative.context import BriefContext, CriticContext, PhenotypeContext, SceneContext
from app.creative.schemas import (
    CriticLLMOutput, ProgramProposal, SceneGraphProposal, SceneZoneProposal,
)
from app.domain.common import NicheRole
from app.domain.phenotype import (
    ConceptPhenotype, PrecedentNote, RationaleLink, VisualDirection,
)
from app.ontology.graph import Ontology

# Title vocabulary. Falls back to the ontology label when a value is not listed.
ADJ = {
    "excavation": "Sunken", "mound": "Raised", "apparition": "Weightless", "veil": "Veiled",
    "vessel": "Held", "clearing": "Open", "threshold": "Crossing", "ascent": "Rising",
    "procession_a": "Processional", "assembly": "Assembled",
    "hovering": "Suspended", "floating_on_water": "Floating", "embedded": "Buried",
    "grounded_mass": "Grounded", "camouflaged": "Dissolved", "bridging": "Spanning",
    "terraced_into": "Terraced", "mirroring": "Mirrored", "framing": "Framing",
    "ignoring_context": "Autonomous",
    "woven": "Woven", "stacked": "Stacked", "carved": "Carved", "cast_monolithic": "Cast",
    "inflated": "Inflated", "draped": "Draped", "tensioned": "Taut", "grown_living": "Living",
    "excavated": "Excavated", "assembled_modular": "Modular",
}
NOUN = {
    "stepped_revolve": "Court", "radial_concentric": "Ring", "spiral_helical": "Spiral",
    "charbagh_orthogonal": "Quadrant", "orthogonal_grid": "Field", "modular_bay": "Colonnade",
    "stepped_orthogonal": "Terraces", "catenary": "Curve", "shell_dome": "Dome",
    "undulating_surface": "Surface", "torus_ring": "Ring", "voronoi_cellular": "Cell",
    "fractal_subdivision": "Lattice", "fragmented_shard": "Shards",
    "stacked_tiers": "Tiers", "suspended_layers": "Canopy",
    "centred_sunken": "Well", "centred_raised": "Platform", "in_the_round": "Arena",
    "frontal_stage": "Stage", "processional_axis": "Passage", "perimeter_ring": "Enclosure",
    "layered_terraces": "Terraces", "dispersed_clusters": "Clearing",
    "concealed_reveal": "Chamber", "asymmetric_focus": "Room",
}
SIGNATURE = {
    "excavation": "sunken", "apparition": "hovering", "mound": "swelling", "veil": "veiled",
    "hovering": "hovering", "floating_on_water": "floating", "embedded": "buried",
    "woven": "woven", "stacked": "stacked", "carved": "carved", "draped": "draped",
    "tensioned": "taut", "inflated": "billowing", "grown_living": "growing",
    "cast_monolithic": "monolithic", "excavated": "cut",
}


def _word(table: dict[str, str], ref: str, ont: Ontology) -> str:
    key = ref.split(":", 1)[-1]
    if key in table:
        return table[key]
    return ont.label(ref).split()[-1].title()


def _signature(ont: Ontology, g) -> str:
    for ref in (g.thesis_archetype.value, g.site_relationship.value, g.tectonic_logic.value):
        key = ref.split(":", 1)[-1]
        if key in SIGNATURE:
            return SIGNATURE[key]
    return ont.label(g.tectonic_logic.value).split()[0].lower()


def make_phenotype_generator(ont: Ontology):
    def gen(context: BaseModel | None, rng: SeededRandom) -> ConceptPhenotype:
        assert isinstance(context, PhenotypeContext)
        g, program = context.genotype, context.program
        L = ont.label
        D = lambda r: (ont.node(r).desc if r in ont.nodes else "")  # noqa: E731

        adj = _word(ADJ, g.thesis_archetype.value, ont)
        if g.site_relationship.value.split(":")[-1] in ADJ and rng.random() < 0.5:
            adj = ADJ[g.site_relationship.value.split(":")[-1]]
        noun = _word(NOUN, g.geometry.system, ont)
        if g.occupation_staging.value.split(":")[-1] in NOUN and rng.random() < 0.45:
            noun = NOUN[g.occupation_staging.value.split(":")[-1]]
        title = context.preserve_title or f"The {adj} {noun}"
        n = 2
        while title in context.sibling_titles:
            title = f"The {adj} {noun} {'I' * n}"
            n += 1

        primary = g.primary_material()
        sig = context.preserve_signature or _signature(ont, g)
        narrative = " then ".join(L(s).lower() for s in g.spatial_narrative)

        one_line = (
            f"{L(g.thesis_archetype.value)} expressed as {L(g.geometry.system).lower()} "
            f"in {L(primary.material).lower()}, {L(g.site_relationship.value).lower()}."
        )
        thesis = (
            f"{D(g.thesis_archetype.value) or L(g.thesis_archetype.value)} "
            f"The organising language is {L(g.architectural_language.value).lower()}: "
            f"{D(g.architectural_language.value).strip()} "
            f"Its geometry is {L(g.geometry.system).lower()} and it stands as "
            f"{L(g.structural_logic.value).lower()}, {L(g.tectonic_logic.value).lower()} in "
            f"{L(primary.material).lower()}. The gathering is {L(g.occupation_staging.value).lower()}, "
            f"reached by a sequence of {narrative}. Light is handled as "
            f"{L(g.lighting_philosophy.value).lower()}, and the whole is pitched at "
            f"{L(g.scale_strategy.value).lower()} scale with a {L(g.emotional_register.value).lower()} "
            f"register. The reading a guest carries away is {sig}."
        )
        if context.principle_statements:
            thesis += f" It works because {context.principle_statements[0]}"

        spatial = (
            f"Arrival is organised as {narrative}. The plan is {L(g.geometry.system).lower()} "
            f"across a {program.site.width_m:.0f} x {program.site.depth_m:.0f} m site, with the "
            f"gathering {L(g.occupation_staging.value).lower()} for {program.capacity.guests} people. "
            f"The structure sits {L(g.site_relationship.value).lower()}."
        )
        others = ", ".join(f"{L(m.material).lower()} ({m.role.value.lower()})"
                           for m in g.material_palette if m.role.value != "PRIMARY")
        material = (
            f"{L(primary.material)} carries the primary surface, worked "
            f"{L(g.tectonic_logic.value).lower()}. Supporting it: {others or 'nothing else'}. "
            f"The structural system is {L(g.structural_logic.value).lower()}"
            + (f", requiring {', '.join(t.split(':')[-1].replace('_',' ') for t in g.technology)}."
               if g.technology else ".")
        )
        experience = (
            f"A guest moves through {narrative}. The space reads as {sig}. "
            f"Under {L(g.lighting_philosophy.value).lower()}, the register is "
            f"{L(g.emotional_register.value).lower()}."
        )

        # rationale must cite REAL constraint ids, so fidelity check F1 passes honestly
        ids = [c.constraint_id for c in program.invariants]
        cap = next((i for i in ids if "capacity" in i), ids[0] if ids else "c_capacity")
        site = next((i for i in ids if "site" in i), cap)
        third = next((i for i in ids if i not in (cap, site)), cap)
        rationale = [
            RationaleLink(move=f"organise the gathering as {L(g.occupation_staging.value).lower()}",
                          because=f"{program.capacity.guests} people must gather with a clear view of the focus",
                          evidence_ref=cap),
            RationaleLink(move=f"set the structure {L(g.site_relationship.value).lower()}",
                          because=f"the {program.site.width_m:.0f} x {program.site.depth_m:.0f} m site "
                                  f"and its {program.site.ground.lower()} ground determine what can be built",
                          evidence_ref=site),
            RationaleLink(move=f"build it {L(g.tectonic_logic.value).lower()} in {L(primary.material).lower()}",
                          because=f"budget band {program.budget.band} and a "
                                  f"{program.schedule.load_in_hours:.0f} hour load-in bound the method",
                          evidence_ref=third),
        ]
        precedents = [
            PrecedentNote(reference=L(c.ref), used_as="PRINCIPLE",
                          not_copied="abstracted to a spatial principle, not quoted as a motif")
            for c in g.cultural_lineage
        ]
        anti = ", ".join(L(a).lower() for a in g.anti_attributes[:4])
        tensions = [t for t in ont.tensions(g.architectural_language.value)
                    if t[0] in set(g.all_refs())]
        reconciliation = None
        if tensions:
            reconciliation = (
                f"{L(g.architectural_language.value)} and {L(tensions[0][0])} belong together here "
                f"because both refuse applied ornament and let the making be the expression."
            )
        return ConceptPhenotype(
            title=title[:64], one_line=one_line[:200], design_thesis=thesis,
            spatial_explanation=spatial, material_explanation=material,
            experience_narrative=experience, rationale_chain=rationale,
            precedent_notes=precedents,
            what_it_is_not=f"Not {anti}." if anti else "Not a decorated version of the expected answer.",
            reconciliation_thesis=reconciliation, signature_read=sig[:40],
            visual_direction=VisualDirection(
                atmosphere=f"{L(g.emotional_register.value).lower()}, {L(g.lighting_philosophy.value).lower()}",
                key_moment=f"the moment of {L(g.spatial_narrative[-1]).lower()}",
                depiction_register="CINEMATIC" if "cinematic" in g.architectural_language.value
                                   else "ARCHITECTURAL_PHOTO",
                palette_words=[L(m.material).lower() for m in g.material_palette][:4]
                              + [L(g.emotional_register.value).lower()],
                avoid_terms=[L(a).lower() for a in g.anti_attributes[:4]],
            ),
        )
    return gen


def make_program_generator(ont: Ontology):
    def gen(context: BaseModel | None, rng: SeededRandom) -> ProgramProposal:
        assert isinstance(context, BriefContext)
        text = context.raw_text.lower()
        intents: list[str] = []
        for kw, intent in (
            ("luxury", "a register of unmistakable material generosity"),
            ("intimate", "closeness between guests and the focus"),
            ("futuristic", "a forward-looking, non-historical language"),
            ("experimental", "a willingness to depart from typological convention"),
            ("modern", "a contemporary rather than revivalist language"),
            ("traditional", "continuity with an inherited spatial language"),
            ("minimal", "restraint and reduction over accumulation"),
            ("dramatic", "high contrast and a staged reveal"),
        ):
            if kw in text:
                intents.append(intent)
        if not intents:
            intents = ["a coherent spatial idea legible in a single view"]
        return ProgramProposal(
            summary=f"Extracted programme for a {context.typology.replace('_', ' ').lower()}.",
            soft_intents=intents, inferred_constraints=[],
        )
    return gen


def make_critic_generator(ont: Ontology, policy: str = "deterministic_only"):
    """Deterministic checks always run for real. This governs only the LLM half."""
    def gen(context: BaseModel | None, rng: SeededRandom) -> CriticLLMOutput:
        assert isinstance(context, CriticContext)
        if policy == "all_pass" or policy == "deterministic_only":
            return CriticLLMOutput(findings=[], notes="mock: no qualitative findings")
        if policy.startswith("fail_rate:"):
            rate = float(policy.split(":", 1)[1])
            if rng.random() < rate:
                from app.creative.schemas import CriticFindingProposal
                from app.domain.evaluation import EvidenceSpan
                return CriticLLMOutput(findings=[CriticFindingProposal(
                    code=f"{context.critic[:4]}_QUALITATIVE_RISK", severity="MINOR",
                    statement="Mock qualitative finding for repair-path exercise.",
                    evidence=[EvidenceSpan(source="PHENOTYPE", path="design_thesis",
                                           excerpt=context.concept.phenotype.one_line[:80])],
                )], notes="mock: injected finding")
        return CriticLLMOutput(findings=[], notes="mock")
    return gen


def make_scene_generator(ont: Ontology):
    def gen(context: BaseModel | None, rng: SeededRandom) -> SceneGraphProposal:
        assert isinstance(context, SceneContext)
        p, g = context.program, context.genotype
        zones = [
            SceneZoneProposal(zone=z.zone, role=z.zone,
                              area_m2=max(z.min_area_m2, 12.0), capacity=z.capacity)
            for z in p.required_zones
        ] or [SceneZoneProposal(zone="main", role="main",
                                area_m2=p.site.usable_area_m2 * 0.4, capacity=p.capacity.guests)]
        if g.site_relationship.value.endswith("embedded") or g.thesis_archetype.value.endswith("excavation"):
            zones = [z.model_copy(update={"level_m": -2.1}) if z.zone in ("ceremony", "main", "stage")
                     else z for z in zones]
        span = next((pp.value for pp in g.geometry.params if pp.name == "span_m"), None)
        return SceneGraphProposal(
            zones=zones, focal_role="focal",
            focal_clearance_radial_m=1.5, focal_clearance_overhead_m=4.0,
            element_height_m=round(2.6 + rng.random() * 3.5, 2),
            element_span_m=round(span or (5.0 + rng.random() * 6.0), 2),
        )
    return gen
