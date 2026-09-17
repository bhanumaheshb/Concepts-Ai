"""The Visual Director.

Answers one question per image, in structure: *if I were directing the visualisation
of this concept, what image would best communicate it?* Only after that does the
prompt compiler put anything into words.

  deterministic direction  — always. Built from the semantic reading (what the event is
                             and what it must communicate), the concept (its DNA and,
                             when written, its prose), the scene graph (what is where)
                             and camera templates keyed by audience and zone role.
  model refinement         — optional, hero view only. A reasoning model may improve the
                             story, composition and depth layers. It may not change the
                             subject, the focus, the zones, or what must be avoided, and
                             anything it writes that names a forbidden element is dropped.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core import logging as elog
from app.domain.brief import DesignProgram
from app.domain.concept import ConceptDNA
from app.domain.providers.protocols import StructuredGenerator
from app.domain.semantics import (
    ElementStatus, LLMCallRecord, ProgramZone, SemanticBrief, display_label,
)
from app.domain.visual import VisualIntent
from app.ontology.graph import Ontology
from app.semantics.knowledge import load_knowledge
from app.semantics.leakage import find_leaks

TEMPLATES = Path(__file__).resolve().parent / "templates.yaml"


@lru_cache(maxsize=1)
def _templates() -> dict:
    return yaml.safe_load(TEMPLATES.read_text(encoding="utf-8"))


class VisualReading(BaseModel):
    """What a reasoning model may contribute to the hero image. Flat, string-typed."""
    model_config = ConfigDict(extra="ignore")
    story_of_image: str = ""
    composition: str = ""
    foreground: str = ""
    midground: str = ""
    background: str = ""
    camera_position: str = ""
    human_activity: str = ""
    lighting: str = ""
    time_of_day: str = ""
    atmosphere: list[str] = Field(default_factory=list)
    important_elements: list[str] = Field(default_factory=list)


VISUAL_SYSTEM = """You are an architectural visualisation director. A design concept has \
already been decided. Decide how ONE hero image should communicate it: what the image is \
about, where the camera is, what sits in the foreground, midground and background, what \
people are doing, and how light reads. Be concrete and spatial. Never introduce an element \
listed under MUST NOT APPEAR, and never change the subject or the focus. Each field is one \
or two sentences. Return only the JSON object."""


class VisualDirector:
    def __init__(self, ont: Ontology, reasoner: StructuredGenerator | None = None) -> None:
        self.ont = ont
        self.reasoner = reasoner
        self.calls: list[LLMCallRecord] = []

    # ------------------------------------------------------------------ public
    def direct(self, *, dna: ConceptDNA, program: DesignProgram, concept=None,
               scene=None) -> list[VisualIntent]:
        """The hero view, one view per zone worth rendering, and the measured drawings."""
        sem = program.semantic
        if sem is None:
            return []
        intents = [self._hero(dna, program, sem, concept, scene)]
        rendered = set(_templates().get("rendered_roles", []))
        primary = sem.intent.primary_zone_key
        for z in sem.programme:
            if z.priority == "optional" or z.role not in rendered:
                continue
            intents.append(self._zone(dna, program, sem, concept, scene, z, is_primary=z.key == primary))
        for axis, label in (("plan", "Plan"), ("front", "Front Elevation"), ("side", "Side Elevation")):
            intents.append(self._drawing(dna, program, sem, axis, label))
        return [self._enforce(sem, i) for i in intents]

    # ---------------------------------------------------------------- the hero
    def _hero(self, dna, program, sem: SemanticBrief, concept, scene) -> VisualIntent:
        t = _templates()["hero_by_audience"].get(sem.profile.audience_relationship,
                                                 _templates()["hero_by_audience"]["none"])
        k = load_knowledge()
        ident = sem.profile.identity
        cap = program.capacity.guests
        focus = sem.primary_zone()
        focus_label = (focus.label if focus else sem.intent.primary_focus) or "the focus"
        people_zone = _people_zone(sem, exclude=focus.key if focus else "")
        g = dna.genotype
        mat = self._label(g.primary_material().material)
        struct = self._label(g.structural_logic.value)
        light = self._label(g.lighting_philosophy.value)
        signature = f"{mat} {struct}"

        label = display_label(ident)
        subject = f"{_article(label).capitalize()} {label} for {cap} people"
        if sem.location:
            subject += f", {sem.location}"
        story = "; ".join(sem.intent.must_communicate[:2]) or sem.profile.focal_relationship
        # the title the client will see: the writer's when it wrote one, else the engine's
        title = (concept.concept_title if concept and concept.concept_title else dna.phenotype.title)
        story = f"{story}, held within {title}: {dna.phenotype.one_line}"

        human = _human_activity(k, [a.key for a in sem.profile.primary_activities])
        # WHEN the event happens is a fact about the event — a Haldi is a morning, a
        # concert is a night. The writer's camera time is a stylistic choice and only
        # fills in when the semantics have nothing to say.
        time_of_day = (_time_of_day(k, sem, strict=True)
                       or (concept.camera_recommendation.time_of_day if concept else "")
                       or "evening")
        lighting = light
        if concept and concept.lighting.lighting_sources:
            lighting = "; ".join(concept.lighting.lighting_sources[:2])

        intent = VisualIntent(
            concept_id=dna.concept_id, view_key="hero", view_label="Hero", zone_key=None,
            visual_subject=subject, story_of_image=story,
            camera_position=t["position"], camera_height_m=float(t["height_m"]),
            lens_mm=int(t["lens_mm"]), field_of_view=t.get("fov", ""),
            view_direction=t.get("direction", ""), composition=t.get("composition", ""),
            foreground=(f"{people_zone.label.lower()}: {_zone_people(k, people_zone)}"
                        if people_zone else human),
            midground=f"the {focus_label.lower()}, defined by the {signature}",
            background=f"the {self._label(g.site_relationship.value)} setting and the "
                       f"{self._label(g.geometry.system)} order of the structure",
            depth="three distinct depth layers, the focus sharpest",
            primary_focal_point=focus_label,
            secondary_focal_points=[z.label for z in sem.programme
                                    if z.priority == "required" and z.key != (focus.key if focus else "")
                                    and z.role not in ("circulation", "service", "technical", "backstage", "arrival")][:2],
            visible_program_zones=_visible(sem, focus),
            important_elements=_important(sem) + [f"the {signature}"],
            elements_to_avoid=list(sem.intent.avoid),
            human_activity=human,
            occupancy=f"in use by a crowd consistent with {cap} people",
            scale_cues=["people at true scale"] + _scale_cues(focus, people_zone),
            material_readability=f"{mat} legible as itself: texture, joints and how light falls on it",
            structural_readability=f"the {struct} readable as what holds the space up"
                                   + (f", spanning about {scene.derived.max_span_m:.0f} m"
                                      if scene is not None and scene.derived.max_span_m else ""),
            lighting=lighting, time_of_day=time_of_day,
            atmosphere=list(dict.fromkeys(sem.intent.experience_goals[:4]
                                          + [self._label(g.emotional_register.value)])),
            provenance={
                "visual_subject": "semantic", "story_of_image": "semantic+concept",
                "camera": f"template:audience={sem.profile.audience_relationship}",
                "foreground": "semantic", "midground": "semantic+genotype",
                "background": "genotype", "human_activity": "semantic",
                "lighting": "concept" if concept and concept.lighting.lighting_sources else "genotype",
                "time_of_day": "semantic" if _time_of_day(k, sem, strict=True) else "concept",
                "elements_to_avoid": "semantic",
            })
        if self.reasoner is not None and self.reasoner.is_configured():
            intent = self._refine(intent, sem, dna, concept)
        return intent

    # ---------------------------------------------------------------- a zone
    def _zone(self, dna, program, sem: SemanticBrief, concept, scene, z: ProgramZone,
              is_primary: bool) -> VisualIntent:
        t = _templates()["zone_by_role"].get(z.role, _templates()["zone_by_role"]["support"])
        k = load_knowledge()
        ident = sem.profile.identity
        g = dna.genotype
        focus = sem.primary_zone()
        area = _named_area(concept, z)
        human = _zone_people(k, z)
        return VisualIntent(
            concept_id=dna.concept_id, view_key=z.key, view_label=z.label, zone_key=z.key,
            visual_subject=f"The {z.label.lower()} of {_article(display_label(ident))} "
                           f"{display_label(ident)} for {program.capacity.guests} people",
            story_of_image=area or f"{z.label}: {z.rationale}",
            camera_position=t["position"], camera_height_m=float(t["height_m"]),
            lens_mm=int(t["lens_mm"]),
            view_direction=f"{t.get('direction', '')}, framing the {z.label.lower()}".strip(", "),
            composition=t.get("composition", ""),
            foreground=human, midground=f"the {z.label.lower()}",
            background=(f"the {focus.label.lower()}" if focus and not is_primary
                        else f"the {self._label(g.structural_logic.value)}"),
            primary_focal_point=z.label,
            secondary_focal_points=[focus.label] if focus and not is_primary else [],
            visible_program_zones=[z.label] + ([focus.label] if focus and not is_primary else []),
            important_elements=_important(sem, zone=z),
            elements_to_avoid=list(sem.intent.avoid),
            human_activity=human,
            occupancy="in use" if z.role not in ("arrival", "circulation") else "people passing through",
            scale_cues=["people at true scale"] + _scale_cues(z, None),
            material_readability=f"{self._label(g.primary_material().material)} legible at close range",
            structural_readability=f"the {self._label(g.structural_logic.value)} visible where it meets this zone",
            lighting=self._label(g.lighting_philosophy.value),
            time_of_day=_time_of_day(k, sem, z),
            atmosphere=sem.intent.experience_goals[:3],
            provenance={"camera": f"template:role={z.role}",
                        "story_of_image": "concept" if area else "semantic",
                        "human_activity": "semantic"})

    def _drawing(self, dna, program, sem: SemanticBrief, axis: str, label: str) -> VisualIntent:
        zones = [z.label for z in sem.programme if z.priority != "optional"]
        return VisualIntent(
            concept_id=dna.concept_id, view_key=f"drawing_{axis}", view_label=label,
            render_intent="orthographic_drawing",
            visual_subject=f"The {label.lower()} of {_article(display_label(sem.profile.identity))} "
                           f"{display_label(sem.profile.identity)}",
            story_of_image="a measured drawing of how the programme is organised",
            camera_position="orthographic, no perspective", composition="flat, centred, to scale",
            visible_program_zones=zones if axis == "plan" else [],
            annotation_requirements=(["zone names", "overall dimensions"] if axis == "plan"
                                     else ["overall width", "overall height"]),
            elements_to_avoid=list(sem.intent.avoid),
            provenance={"visible_program_zones": "semantic", "camera": "template:drawing"})

    # --------------------------------------------------------- model refinement
    def _refine(self, intent: VisualIntent, sem: SemanticBrief, dna, concept) -> VisualIntent:
        forbidden = [e.label for e in sem.profile.elements if e.status == ElementStatus.FORBIDDEN
                     and ("neighbouring" in e.rationale or e.provenance.value == "USER_EXPLICIT")]
        user = "\n".join([
            "## SUBJECT (fixed)", intent.visual_subject, "",
            "## WHAT THE IMAGE MUST COMMUNICATE", *[f"- {m}" for m in sem.intent.must_communicate],
            "", "## FOCUS (fixed)", intent.primary_focal_point, "",
            "## CONCEPT", f"{dna.phenotype.title}: {dna.phenotype.one_line}",
            (concept.concept_thesis if concept else dna.phenotype.design_thesis), "",
            "## ZONES IN VIEW", *[f"- {z}" for z in intent.visible_program_zones], "",
            "## CURRENT DIRECTION",
            f"camera: {intent.camera_phrase()}", f"layers: {intent.layers_phrase()}",
            f"people: {intent.human_activity}", f"light: {intent.lighting}, {intent.time_of_day}", "",
            "## MUST NOT APPEAR", ", ".join(forbidden) or "(nothing listed)", "",
            "## TASK", "Improve the direction of this one hero image. Return the JSON object.",
        ])
        res = self.reasoner.generate(stage="14c", purpose=f"visual direction for {dna.concept_id}",
                                     system=VISUAL_SYSTEM, user=user, schema=VisualReading,
                                     max_output_tokens=1024)
        self.calls.append(res.record)
        if res.value is None:
            return intent.model_copy(update={"overridden": intent.overridden + [
                f"visual reasoner failed: {res.record.error}"]})
        k = load_knowledge()
        update, dropped, prov = {}, [], dict(intent.provenance)
        for field in ("story_of_image", "composition", "foreground", "midground", "background",
                      "camera_position", "human_activity", "lighting", "time_of_day"):
            val = " ".join(str(getattr(res.value, field) or "").split())
            if not val:
                continue
            leaks = find_leaks(k, sem.profile, val, f"visual.{field}")
            if leaks:
                dropped.append(f"{field} rejected: {leaks[0].describe()}")
                continue
            update[field], prov[field] = val[:400], "llm"
        extra = [s for s in res.value.important_elements[:4]
                 if s and not find_leaks(k, sem.profile, s, "visual.important_elements")]
        if extra:
            update["important_elements"] = intent.important_elements + extra
        update["provenance"] = prov
        update["overridden"] = intent.overridden + dropped
        return intent.model_copy(update=update)

    # ------------------------------------------------------------ invariants
    def _enforce(self, sem: SemanticBrief, intent: VisualIntent) -> VisualIntent:
        """Last line: no field of a visual intent may name a forbidden element, whoever
        wrote it. A field that leaks is emptied and the reason recorded."""
        k = load_knowledge()
        update, dropped = {}, []
        for field in ("visual_subject", "story_of_image", "composition", "foreground",
                      "midground", "background", "human_activity", "lighting",
                      "primary_focal_point"):
            val = getattr(intent, field)
            leaks = find_leaks(k, sem.profile, val, f"visual.{field}")
            if leaks:
                update[field] = ""
                dropped.append(f"{field} emptied: {leaks[0].describe()}")
        for field in ("important_elements", "secondary_focal_points", "visible_program_zones"):
            vals = getattr(intent, field)
            kept = [v for v in vals if not find_leaks(k, sem.profile, v, field)]
            if len(kept) != len(vals):
                update[field] = kept
                dropped.append(f"{field}: {len(vals) - len(kept)} item(s) removed as leakage")
        if not update:
            return intent
        update["overridden"] = intent.overridden + dropped
        return intent.model_copy(update=update)

    def _label(self, ref: str) -> str:
        node = self.ont.nodes.get(ref)
        return node.label.lower() if node else ref.split(":")[-1].replace("_", " ")


# ────────────────────────────────── helpers ──────────────────────────────────

def _article(label: str) -> str:
    return "an" if label[:1].lower() in "aeiou" else "a"


def _people_zone(sem: SemanticBrief, exclude: str = "") -> ProgramZone | None:
    people = [z for z in sem.programme if z.key != exclude and z.priority != "optional"
              and z.role in ("audience", "participation", "social", "dining", "display")]
    return max(people, key=lambda z: z.capacity_share, default=None)


def _visible(sem: SemanticBrief, focus: ProgramZone | None) -> list[str]:
    out = [focus.label] if focus else []
    for z in sem.programme:
        if z.priority == "required" and z.role in ("audience", "participation", "social",
                                                    "dining", "display", "hospitality", "performance"):
            if z.label not in out:
                out.append(z.label)
    return out[:4]


def _important(sem: SemanticBrief, zone: ProgramZone | None = None) -> list[str]:
    k = load_knowledge()
    out = []
    for e in sem.profile.elements:
        if e.status not in (ElementStatus.REQUIRED, ElementStatus.RECOMMENDED):
            continue
        el = k.elements.get(e.key)
        if el is None or not el.physical:
            continue
        if zone is not None and (el.zone is None or el.zone.key != zone.key):
            continue
        out.append(e.label)
    return out[:5]


def _human_activity(k, activity_keys: list[str]) -> str:
    phrases = [k.activities[a].human_activity for a in activity_keys
               if a in k.activities and k.activities[a].human_activity]
    return "; ".join(phrases[:2])


def _zone_people(k, z: ProgramZone | None) -> str:
    if z is None:
        return ""
    if z.activity and z.activity in k.activities and k.activities[z.activity].human_activity:
        return k.activities[z.activity].human_activity
    return {"arrival": "guests arriving", "circulation": "people moving through",
            "audience": "people seated, facing the focus", "social": "people in conversation",
            "dining": "guests at tables", "display": "visitors looking closely",
            "hospitality": "guests being served"}.get(z.role, "people using the space")


def _time_of_day(k, sem: SemanticBrief, zone: ProgramZone | None = None,
                 strict: bool = False) -> str:
    keys = ([zone.activity] if zone and zone.activity else []) + [a.key for a in sem.profile.primary_activities]
    for key in keys:
        if key in k.activities and k.activities[key].time_of_day:
            return k.activities[key].time_of_day
    return "" if strict else "evening"


def _scale_cues(*zones) -> list[str]:
    cues = _templates().get("scale_cues_by_role", {})
    out = []
    for z in zones:
        if z is not None:
            out += cues.get(z.role, [])
    return out[:3]


def _named_area(concept, z: ProgramZone) -> str:
    """What the writer actually said about this zone, when it said anything."""
    if concept is None:
        return ""
    for entry in concept.program.additional_zones or []:
        head, _, tail = str(entry).partition(":")
        h = head.strip().lower()
        if h and (h in z.label.lower() or z.label.lower() in h or h.replace(" ", "_") == z.key):
            return (tail.strip() or str(entry))[:300]
    if z.role in ("performance", "ceremony", "focal") and concept.program.focal_space:
        return concept.program.focal_space[:300]
    if z.role == "audience" and concept.program.seating:
        return concept.program.seating[:300]
    if z.role == "arrival" and concept.program.arrival:
        return concept.program.arrival[:300]
    if z.role == "circulation" and concept.program.circulation:
        return concept.program.circulation[:300]
    return ""


def log_intent(i: VisualIntent, title: str = "") -> None:
    try:
        elog.note(f"       {title or i.concept_id} [{i.view_key}] subject={i.visual_subject[:70]!r}")
        elog.note(f"         camera : {i.camera_phrase()[:110]}")
        elog.note(f"         focus  : {i.primary_focal_point} | zones: {', '.join(i.visible_program_zones[:4])}")
        elog.note(f"         people : {i.human_activity[:100]}  ({i.time_of_day})")
        if i.overridden:
            elog.warn(f"         dropped: {'; '.join(i.overridden)[:140]}")
    except Exception:                                  # pragma: no cover
        pass
