"""MockCreativeProvider — deterministic synthesis with no model and no network.

Like the existing mock LLM, this is not filler: every sentence is derived from the
solved genotype using the ontology's own descriptions, so ten different genotypes
produce ten visibly different concepts. That is what keeps the validator, the compiler
and the critics genuinely exercised when no local model is running, and it is why
`LLM_PROVIDER=mock` remains a first-class mode rather than a degraded one.
"""
from __future__ import annotations

from app.creative.synthesis_prompt import geometry_reading
from app.domain.synthesis import (
    CameraRecommendation, LightingBlock, MaterialsBlock, ProgramResolution,
    SpatialSequenceStep, StructuredArchitecturalConcept, StructureBlock,
)
from app.ontology.graph import Ontology

SEQUENCE_WORDS = {
    "arrival": "ARRIVAL", "approach": "ARRIVAL", "threshold": "THRESHOLD",
    "enclosure": "ENCLOSURE", "compression": "COMPRESSION", "release": "RELEASE",
    "ascent": "ASCENT", "descent": "DESCENT", "reveal": "REVEAL", "focus": "FOCUS",
    "procession": "MOVEMENT", "orientation": "ORIENTATION",
}
FOCAL_BY_TYPOLOGY = {
    "WEDDING_MANDAP": "mandap", "EVENT_STAGE": "stage", "RESTAURANT": "open kitchen",
    "EXHIBITION": "principal vitrine", "PAVILION": "central void",
    "INTERIOR": "hearth", "GENERIC_SPATIAL": "focal platform",
}


class MockCreativeProvider:
    name = "mock"
    model = "deterministic"

    def __init__(self, ont: Ontology) -> None:
        self.ont = ont
        self.calls = 0
        self.last_prompt = ""
        self.last_raw: dict | None = None

    def is_configured(self) -> bool:
        return True

    def _label(self, ref: str) -> str:
        node = self.ont.nodes.get(ref)
        return node.label.lower() if node else ref.split(":")[-1].replace("_", " ")

    def _desc(self, ref: str) -> str:
        node = self.ont.nodes.get(ref)
        return (node.desc or node.label).rstrip(".").lower() if node else self._label(ref)

    def synthesize_concept(self, *, concept_dna, brief, program, constraints,
                           reference_context=None, trend_context=None,
                           repair_of=None, repair_instruction: str = "",
                           seed: int = 0) -> StructuredArchitecturalConcept:
        self.calls += 1
        g = concept_dna.genotype
        lang = self._label(g.architectural_language.value)
        struct = self._label(g.structural_logic.value)
        tect = self._label(g.tectonic_logic.value)
        light = self._label(g.lighting_philosophy.value)
        mood = self._label(g.emotional_register.value)
        site_rel = self._label(g.site_relationship.value)
        scale = self._label(g.scale_strategy.value)
        staging = self._label(g.occupation_staging.value)
        geo_refs = (g.geometry.system if isinstance(g.geometry.system, list)
                    else [g.geometry.system])
        geo = ", ".join(self._label(r) for r in geo_refs)
        readings = geometry_reading(geo_refs) or [f"{geo} organised as built form"]
        primary = next(m for m in g.material_palette if m.role.value == "PRIMARY")
        prim = self._label(primary.material)
        others = [self._label(m.material) for m in g.material_palette
                  if m.material != primary.material]

        seq: list[SpatialSequenceStep] = []
        for ref in g.spatial_narrative:
            token = ref.split(":")[-1].lower()
            step = next((v for k, v in SEQUENCE_WORDS.items() if k in token),
                        token.replace("_", " ").upper())
            seq.append(SpatialSequenceStep(
                step=step,
                description=f"the visitor experiences {self._desc(ref)} before the "
                            f"next move is offered"))
        while len(seq) < 3:
            missing = [("THRESHOLD", "the edge is crossed and the outside is left behind"),
                       ("FOCUS", f"attention settles on the {scale} centre"),
                       ("EXIT", "the route releases back toward the approach")]
            step, desc = missing[len(seq) % 3]
            if step not in {s.step for s in seq}:
                seq.append(SpatialSequenceStep(step=step, description=desc))
            else:
                seq.append(SpatialSequenceStep(
                    step=f"MOVEMENT {len(seq)}",
                    description="the route continues along the principal axis"))

        cap = constraints.capacity or 100
        focal_label = FOCAL_BY_TYPOLOGY.get(constraints.typology, "focal platform")
        dims = constraints.site_dimensions or "the given site"

        return StructuredArchitecturalConcept(
            concept_title=f"The {lang.title()} {geo.split(',')[0].title()}",
            concept_thesis=(
                f"A {lang} reading of the brief in which {readings[0]}, so that the "
                f"gathering is held by the architecture rather than decorated by it."),
            design_story=(
                f"The scheme takes {lang} as its organising language and builds it from "
                f"{struct} in {prim}. {readings[0].capitalize()}. The result reads as "
                f"{mood}, and its {site_rel} keeps the {scale} of the room legible from "
                f"the moment of arrival."),
            architectural_language=(
                f"{lang}, resolved architecturally as {readings[0]}"),
            spatial_organization=(
                f"The plan is organised as {geo}: {readings[-1]}. Occupation is "
                f"{staging}, which sets where the crowd stands and where it cannot."),
            arrival_sequence=(
                f"Approach is {site_rel}; the visitor meets the {tect} edge before any "
                f"interior is visible, and the {focal_label} is withheld until the "
                f"threshold is crossed."),
            circulation=(
                f"Movement follows the {geo} order, with the principal route kept clear "
                f"for {cap} people and secondary routes running behind the seating."),
            spatial_sequence=seq,
            program=ProgramResolution(
                focal_space=(f"A {focal_label} of {prim} sits at the centre of the "
                             f"{geo} order, raised enough to be seen from the perimeter."),
                focal_space_label=focal_label,
                seating=(f"Seating for {cap} is arranged so every position holds an "
                         f"unobstructed sightline to the {focal_label}."),
                walkway=(f"A single processional walkway runs from the arrival edge to "
                         f"the {focal_label}, wide enough for two abreast."),
                arrival=(f"Arrival is {site_rel}, compressing before the room opens."),
                circulation=(f"Perimeter circulation runs behind the seating so guests "
                             f"move without crossing the ceremonial route."),
                service_access=("A discreet service route reaches the rear of the "
                                "focal space out of guest sightlines."),
                sightlines=(f"All {cap} sightlines converge on the {focal_label}."),
                spatial_hierarchy=(f"{focal_label} first, seating second, circulation "
                                   f"last."),
            ),
            structure=StructureBlock(
                structural_system=(f"{struct.capitalize()} carried out in {prim}, with "
                                   f"load taken to discrete points at the perimeter."),
                geometry=f"{geo}: {readings[0]}",
                mass_and_void=(f"Mass is concentrated at the {tect} edge; the void is "
                               f"the {scale} centre the gathering occupies."),
                module=(f"One repeated {tect} bay, set out on the {geo} grid and "
                        f"fabricated off site."),
                spans_and_supports=("Bays span 6 m between supports, within the "
                                    "capability of the primary material."),
                joints_and_assembly=("Dry mechanical joints throughout, so the assembly "
                                     "can be struck and re-erected without loss."),
            ),
            materials=MaterialsBlock(
                primary=prim,
                material_behaviour=(f"{prim.capitalize()} carries the primary mass and "
                                    f"holds low-angle light across its face, so the "
                                    f"surface reads differently at each hour."),
                surface_treatment=(f"Left largely as found, with {tect} joints exposed "
                                   f"rather than concealed."),
                secondary=others,
                palette_note=(f"{prim.capitalize()} dominates; "
                              + (", ".join(others) + " appear only where they are "
                                 "structurally justified." if others else
                                 "no secondary material is introduced.")),
            ),
            lighting=LightingBlock(
                lighting_sources=[f"{light} sources", "low perimeter fixtures"],
                colour_temperature="2200K at the focal space against a cooler 4000K field",
                height_and_distribution=(f"Sources sit low at the perimeter and wash "
                                         f"upward across the {prim} face, leaving the "
                                         f"centre brighter than its edge."),
                shadow_behaviour=(f"Shadows are long and directional, describing the "
                                  f"{tect} module rather than flattening it."),
                interaction_with_materials=(f"Grazing light exaggerates the texture of "
                                            f"{prim} and keeps the joints legible."),
            ),
            atmosphere=f"{mood}, held rather than staged",
            landscape=(f"The setting is treated {site_rel}, with planting kept low so "
                       f"the {geo} order stays readable."),
            human_experience=(
                f"A guest arrives {site_rel}, is compressed at the threshold, and only "
                f"then sees the {focal_label} across the {scale} room."),
            camera_recommendation=CameraRecommendation(
                viewpoint="three-quarter approach view along the processional axis",
                height="1.6 m eye height", lens="35 mm",
                orientation="landscape", distance=f"far enough to hold {dims} in frame",
                framing=f"the full {geo} sweep with the {focal_label} off centre",
                time_of_day="blue hour, with the interior sources dominant"),
            construction_character=(
                f"Buildable as a demountable {tect} assembly: repeated bays, dry joints, "
                f"and a load-in that does not require heavy plant."),
            distinctive_elements=[f"the {tect} edge", f"the {prim} {focal_label}",
                                  readings[0]],
            anti_cliches=["no applied floral decoration", "no generic palace imagery",
                          "no symmetrical backdrop wall", "no fantasy or floating form"],
            rationale=(
                f"Every move above follows the solved concept: {lang} sets the language, "
                f"{geo} sets the plan, {struct} sets the load path, {prim} sets the "
                f"surface, and {light} sets how the room is read."),
            source="mock", model="deterministic",
            repaired=bool(repair_instruction),
        )
