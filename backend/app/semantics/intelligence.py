"""Design Intelligence — understand the brief before the creative search starts.

Three passes, in a fixed order of authority:

  1. GROUNDING (deterministic). What the user explicitly said or selected: the event
     named, the tradition stated, the activities and elements mentioned — and the
     ones excluded ("no bar"). Resolved against the knowledge base.
  2. REASONING (optional model). What the brief implies: activities, zones, focus,
     atmosphere, what to avoid — especially for events the knowledge base has never
     seen. Returned in a schema and treated as a proposal.
  3. MERGE under invariants. Precedence is
         user explicit  >  scope rules  >  domain knowledge  >  model inference
     A model may add a zone, an activity or a prohibition. It may not remove what the
     user asked for, and it may not introduce an element outside that element's scope.
     Every rejection is recorded on the trace.

With no reasoning model the reading is deterministic and says so. It never pretends.
"""
from __future__ import annotations

import re

from app.core import logging as elog
from app.domain.brief import DesignBrief
from app.domain.common import EventType as LegacyEvent, Tradition as LegacyTradition, Typology
from app.domain.providers.protocols import StructuredGenerator
from app.domain.semantics import (
    DesignIntent, ElementStatus, EventIdentity, EventProfile, LLMCallRecord, ProgramZone,
    Provenance, ReasonerTrace, SemanticBrief, SemanticElement, SemanticInvariant, SemanticItem,
)
from app.semantics import reading as R
from app.semantics.knowledge import Knowledge, load_knowledge, normalise, slugify
from app.semantics.leakage import find_leaks
from app.semantics.programme import infer_programme
from app.semantics.scope import ScopeContext, element_verdict

AUDIENCE_VALUES = ("frontal", "surround", "immersive", "distributed", "participatory",
                   "processional", "convivial", "none")
# When several activities disagree about where attention goes, the more spatially
# demanding relationship leads: an immersive projection outranks the lounge around it.
AUDIENCE_PRECEDENCE = ("immersive", "surround", "processional", "frontal", "participatory",
                       "distributed", "convivial", "none")
ZONE_ROLES = ("arrival", "focal", "performance", "audience", "participation", "social",
              "hospitality", "dining", "display", "ceremony", "circulation", "service",
              "technical", "backstage", "media", "support", "outdoor", "retail", "work")
# Register words are language, not domain knowledge: they describe any brief.
ATMOSPHERE_WORDS = ("immersive", "intimate", "luxury", "luxurious", "minimalist", "minimal",
                    "grand", "playful", "dramatic", "serene", "futuristic", "traditional",
                    "modern", "rustic", "elegant", "vibrant", "moody", "festive",
                    "contemplative", "sustainable", "experimental", "industrial", "whimsical",
                    "regal", "understated", "bold", "cinematic", "ethereal", "earthy", "calm",
                    "energetic", "informal", "formal", "joyful", "sophisticated", "raw",
                    "tech", "technology", "high-tech", "natural", "botanical", "nocturnal")
LEGACY_TYPOLOGY_EVENT = {
    Typology.WEDDING_MANDAP: "wedding_ceremony", Typology.RESTAURANT: "restaurant",
    Typology.EXHIBITION: "exhibition", Typology.PAVILION: "pavilion",
}
_LEAD = re.compile(r"^(?:an?|the|our|my|a\s+\d[\d,]*[-\s]*(?:person|people|guest|pax)s?)\s+")
_VENUE_SUFFIX = re.compile(r"^[\s-]+(?:halls?|rooms?|cent(?:er|re)s?|venues?|buildings?)\b")


class DesignIntelligence:
    def __init__(self, knowledge: Knowledge | None = None,
                 reasoner: StructuredGenerator | None = None) -> None:
        self.k = knowledge or load_knowledge()
        self.reasoner = reasoner
        self.calls: list[LLMCallRecord] = []

    # ------------------------------------------------------------------ entry
    def understand(self, brief: DesignBrief, capacity: int | None = None) -> SemanticBrief:
        g = self._ground(brief)
        reading, trace = None, ReasonerTrace(source="DETERMINISTIC")
        if self.reasoner is not None and self.reasoner.is_configured():
            reading, trace = self._reason(brief, g)
        return self._assemble(brief, g, reading, trace, capacity)

    # -------------------------------------------------------------- grounding
    def _ground(self, brief: DesignBrief) -> dict:
        k = self.k
        text = " ".join(filter(None, [brief.raw_text, brief.constraints_text]))
        uncertain: list[str] = []

        # -- event identity: the brief's own words, then the form, then legacy typology
        # An event word used as a venue modifier is not the event being designed:
        # "wedding in a convention hall" must not become a conference.
        normalised_text = normalise(text)
        venue_spans = []
        for hit in k.event_index.find(text) + k.family_alias_index.find(text):
            suffix = _VENUE_SUFFIX.match(normalised_text[hit.end:])
            if suffix:
                venue_spans.append((hit.start, hit.end + suffix.end()))
        ev_hits = [m for m in k.event_index.find(text, masked=venue_spans) if not m.negated]
        text_event = max(ev_hits, key=lambda m: (len(m.phrase), -m.start)).key if ev_hits else None
        if text_event is None:
            fam_hits = [m for m in k.family_alias_index.find(text, masked=venue_spans) if not m.negated]
            text_event = fam_hits[0].key if fam_hits else None
            family_only = text_event is not None
        else:
            family_only = False

        ui_raw = brief.event_type_text or (
            brief.event_type.value if brief.event_type != LegacyEvent.GENERIC_EVENT else None)
        ui_event = k.resolve_event_key(ui_raw) if ui_raw else None

        event_key, event_prov, unknown_label = None, Provenance.DETERMINISTIC_RULE, None
        if text_event and ui_event and text_event != ui_event:
            if family_only:
                event_key, event_prov = ui_event, Provenance.USER_EXPLICIT
            else:
                event_key, event_prov = text_event, Provenance.USER_EXPLICIT
                uncertain.append(f"the form selected '{ui_raw}' but the brief names "
                                 f"'{k.event_types[text_event].label}'; the brief was followed")
        elif text_event or ui_event:
            event_key, event_prov = (text_event or ui_event), Provenance.USER_EXPLICIT
        elif ui_raw:
            unknown_label, event_prov = ui_raw.strip(), Provenance.USER_EXPLICIT
        elif brief.typology in LEGACY_TYPOLOGY_EVENT:
            event_key, event_prov = LEGACY_TYPOLOGY_EVENT[brief.typology], Provenance.DETERMINISTIC_RULE
        if event_key is None and unknown_label is None:
            unknown_label = _unknown_label(brief.raw_text)
            event_prov = Provenance.SEMANTIC_INFERENCE

        et = k.event_types.get(event_key or "")
        # masking the event's own phrase stops "Haldi ceremony" also reading as a ceremony
        masked = venue_spans + [(m.start, m.end) for m in ev_hits if m.key == event_key]

        # -- tradition: stated or selected, never guessed
        tradition = None
        if brief.tradition not in (LegacyTradition.UNSPECIFIED,):
            tradition = brief.tradition.value.lower()
        else:
            t_hits = [m for m in k.tradition_index.find(text) if not m.negated]
            tradition = t_hits[0].key if t_hits else None

        # -- activities the brief names
        suppressed = set(et.suppress_activities) if et else set()
        act_hits = k.activity_index.find(text, masked=masked)
        explicit_acts, excluded_acts = [], set()
        for m in act_hits:
            if m.negated:
                excluded_acts.add(m.key)
            elif m.key not in suppressed and m.key not in explicit_acts:
                explicit_acts.append(m.key)

        # -- elements the brief names, or excludes
        el_hits = k.element_index.find(text)
        requested, excluded = [], []
        for m in el_hits:
            (excluded if m.negated else requested).append(m.key)

        atmosphere = []
        low = normalise(text)
        for w in ATMOSPHERE_WORDS:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) and w not in atmosphere:
                atmosphere.append(w)

        return dict(text=text, event_key=event_key, event_prov=event_prov,
                    unknown_label=unknown_label, tradition=tradition,
                    explicit_acts=explicit_acts, excluded_acts=excluded_acts,
                    requested=list(dict.fromkeys(requested)),
                    excluded=list(dict.fromkeys(excluded)),
                    atmosphere=atmosphere, uncertain=uncertain)

    # -------------------------------------------------------------- reasoning
    def _reason(self, brief: DesignBrief, g: dict) -> tuple[R.SemanticReading | None, ReasonerTrace]:
        k = self.k
        et = k.event_types.get(g["event_key"] or "")
        grounding = {
            "event type": et.label if et else f"not in the knowledge base ({g['unknown_label']})",
            "tradition": g["tradition"] or "not stated — do not assume one",
            "activities named in the brief": ", ".join(g["explicit_acts"]),
            "elements requested": ", ".join(g["requested"]),
            "elements excluded by the user": ", ".join(g["excluded"]),
        }
        selections = {"event": brief.event_type_text or "",
                      "venue": brief.venue_type.value if brief.venue_type else "",
                      "location": brief.location or "", "dimensions": brief.dimensions_text or ""}
        user = R.build_user_prompt(brief_text=g["text"], selections=selections,
                                   grounding=grounding, activity_keys=sorted(k.activities),
                                   family_keys=sorted(k.families))
        res = self.reasoner.generate(stage="01", purpose="semantic reading of the brief",
                                     system=R.SYSTEM, user=user, schema=R.SemanticReading,
                                     max_output_tokens=2048)
        self.calls.append(res.record)
        rec = res.record
        trace = ReasonerTrace(source="MERGED" if res.value is not None else "DETERMINISTIC",
                              model=rec.model, latency_ms=rec.latency_ms,
                              attempts=rec.attempts, error=rec.error)
        return res.value, trace

    # ---------------------------------------------------------------- assembly
    def _assemble(self, brief: DesignBrief, g: dict, reading: R.SemanticReading | None,
                  trace: ReasonerTrace, capacity: int | None) -> SemanticBrief:
        k = self.k
        overridden = list(trace.overridden)
        uncertain = list(g["uncertain"])
        et = k.event_types.get(g["event_key"] or "")
        tb = et.traditions.get(g["tradition"] or "") if et else None

        # ---- identity
        if et is not None:
            identity = EventIdentity(
                domain=et.domain, event_family=et.family or None, event_type=et.key,
                event_type_label=tb.label if tb else et.label, tradition=g["tradition"],
                proper_name=bool(tb) or et.proper_name,
                culture=brief.location, known_type=True, provenance=g["event_prov"],
                confidence=0.95 if g["event_prov"] == Provenance.USER_EXPLICIT else 0.7,
                venue_type=_venue(brief))
        else:
            # The user's own name for an unknown event outranks a model's paraphrase of
            # it. The paraphrase is kept as the subtype, where it informs without replacing.
            own = g["unknown_label"] if g["unknown_label"] not in ("", "unspecified brief") else ""
            model_label = reading.event_type_label.strip() if reading and reading.event_type_label else ""
            label = own or model_label or "Unspecified brief"
            fam = _known_family(k, reading.event_family) if reading and reading.event_family else None
            if reading and reading.event_family and fam is None:
                uncertain.append(f"proposed family '{reading.event_family[:60]}' is not in the "
                                 "knowledge base; no family assumed")
            domain = slugify(reading.domain) if reading and reading.domain else "event"
            identity = EventIdentity(
                domain=domain if domain in ("event", "interior", "architecture", "installation",
                                            "landscape") else "event",
                event_family=fam, event_type=slugify(label), event_type_label=label[:1].upper() + label[1:],
                subtype=((reading.subtype or (model_label if model_label and model_label != label else ""))
                         or None) if reading else None,
                tradition=g["tradition"], culture=brief.location, known_type=False,
                provenance=(g["event_prov"] if own else
                            Provenance.LLM_INFERENCE if model_label else g["event_prov"]),
                confidence=0.6 if reading else 0.4, venue_type=_venue(brief))
            if not reading:
                uncertain.append("event type not in the knowledge base; programme inferred "
                                 "from the activities the brief names")
        ctx = ScopeContext(event_type=identity.event_type, family=identity.event_family,
                           tradition=identity.tradition)

        # ---- activities
        primary: list[SemanticItem] = []
        secondary: list[SemanticItem] = []

        def act_item(key: str, prov: Provenance, why: str) -> SemanticItem:
            a = k.activities.get(key)
            return SemanticItem(key=slugify(key), label=a.label if a else key.replace("_", " "),
                                provenance=prov, rationale=why,
                                confidence=0.9 if prov != Provenance.LLM_INFERENCE else 0.6)

        seen: set[str] = set()
        if et:
            for a in et.primary_activities:
                if a not in g["excluded_acts"]:
                    primary.append(act_item(a, Provenance.DOMAIN_KNOWLEDGE, f"what a {et.label} is"))
                    seen.add(a)
            for a in et.secondary_activities:
                if a not in g["excluded_acts"]:
                    secondary.append(act_item(a, Provenance.DOMAIN_KNOWLEDGE, f"common at a {et.label}"))
                    seen.add(a)
        for a in g["explicit_acts"]:
            if a in seen:
                continue
            item = act_item(a, Provenance.USER_EXPLICIT, "named in the brief")
            (secondary if et else primary).append(item)
            seen.add(a)
        if reading:
            suppressed = set(et.suppress_activities) if et else set()
            for bucket, target in ((reading.primary_activities, primary if not et else secondary),
                                   (reading.secondary_activities, secondary)):
                for raw in bucket:
                    key = slugify(raw)
                    if key in seen:
                        continue
                    if key in suppressed or key in g["excluded_acts"]:
                        overridden.append(f"activity '{key}' rejected: excluded for this event")
                        continue
                    target.append(act_item(key, Provenance.LLM_INFERENCE, "inferred by the reasoning model"))
                    seen.add(key)
        if not primary and not secondary:
            primary.append(act_item("celebration", Provenance.DETERMINISTIC_RULE,
                                    "no activity could be identified; a gathering is assumed"))
            uncertain.append("no activity was identifiable in the brief")

        # ---- audience relationship
        if et:
            audience = et.audience
        else:
            votes = [k.activities[i.key].audience for i in primary + secondary
                     if i.key in k.activities]
            if reading and reading.audience_relationship in AUDIENCE_VALUES:
                votes.insert(0, reading.audience_relationship)
            audience = next((a for a in AUDIENCE_PRECEDENCE if a in votes), "none")

        # ---- elements
        elements: dict[str, SemanticElement] = {}

        def put(key: str, status: ElementStatus, prov: Provenance, why: str, rule: str = "") -> None:
            el = k.elements.get(key)
            elements[key] = SemanticElement(key=key, label=el.label if el else key.replace("_", " "),
                                            status=status, provenance=prov, rationale=why, rule=rule)

        if et:
            for status, keys in ((ElementStatus.REQUIRED, et.elements["required"]),
                                 (ElementStatus.RECOMMENDED, et.elements["recommended"]),
                                 (ElementStatus.OPTIONAL, et.elements["optional"])):
                for key in keys:
                    put(key, status, Provenance.DOMAIN_KNOWLEDGE, f"part of a {et.label}")
        if tb:
            for status, keys in ((ElementStatus.REQUIRED, tb.elements["required"]),
                                 (ElementStatus.RECOMMENDED, tb.elements["recommended"]),
                                 (ElementStatus.OPTIONAL, tb.elements["optional"])):
                for key in keys:
                    put(key, status, Provenance.DOMAIN_KNOWLEDGE, f"part of a {tb.label}")
        if reading:
            for status, bucket in ((ElementStatus.REQUIRED, reading.required_elements),
                                   (ElementStatus.RECOMMENDED, reading.recommended_elements),
                                   (ElementStatus.OPTIONAL, reading.optional_elements)):
                for phrase in bucket:
                    for m in k.element_index.find(phrase):
                        if m.negated or m.key in elements:
                            continue
                        # a model's "required" never outranks the knowledge base
                        put(m.key, ElementStatus.RECOMMENDED if et and status == ElementStatus.REQUIRED
                            else status, Provenance.LLM_INFERENCE, "inferred by the reasoning model")
            for phrase in reading.forbidden_elements:
                for m in k.element_index.find(phrase):
                    el = k.elements[m.key]
                    implied = el.zone is not None and any(
                        el.zone.key == z.key for i in primary + secondary if i.key in k.activities
                        for z in k.activities[i.key].zones)
                    if implied:
                        overridden.append(f"forbidding '{m.key}' rejected: the brief's own "
                                          "activities require it")
                        continue
                    if m.key not in g["requested"] and m.key not in elements:
                        put(m.key, ElementStatus.FORBIDDEN, Provenance.LLM_INFERENCE,
                            "the reasoning model judged it foreign to this event")

        # scope: every scoped element is judged, whether or not anyone mentioned it
        for key, el in k.elements.items():
            verdict = element_verdict(k, el, ctx)
            if verdict.status is None:
                continue
            cur = elements.get(key)
            if cur and cur.provenance == Provenance.DOMAIN_KNOWLEDGE and cur.status != ElementStatus.FORBIDDEN:
                continue       # the knowledge base placed it here deliberately
            if cur and cur.provenance == Provenance.LLM_INFERENCE and cur.status != ElementStatus.FORBIDDEN:
                overridden.append(f"element '{key}' rejected: {verdict.rule}")
            put(key, verdict.status, Provenance.DETERMINISTIC_RULE,
                ("likely confusion with a neighbouring event" if verdict.near_miss
                 else "does not belong to this event"), rule=verdict.rule)

        # the user's own words override everything above
        for key in g["requested"]:
            el = k.elements[key]
            prev = elements.get(key)
            if not el.physical:
                if prev is None or prev.status != ElementStatus.FORBIDDEN:
                    put(key, ElementStatus.CONTEXTUAL, Provenance.USER_EXPLICIT, "mentioned as context")
                continue
            rule = "user_explicit"
            if prev and prev.status == ElementStatus.FORBIDDEN:
                rule = f"user_explicit overrides {prev.rule or 'a default prohibition'}"
            put(key, ElementStatus.REQUIRED, Provenance.USER_EXPLICIT, "requested in the brief", rule)
        for key in g["excluded"]:
            put(key, ElementStatus.FORBIDDEN, Provenance.USER_EXPLICIT, "excluded in the brief",
                "user_excluded")
        # An explicit request carries the place it occupies with it. A requested mandap
        # IS the ceremony focus of this plan, so the generic ceremony focus can no longer
        # be forbidden by scope — otherwise the user's own request is rejected as a leak.
        requested_zones = {k.elements[key].zone.key for key in g["requested"]
                           if key in k.elements and k.elements[key].zone
                           and elements.get(key) and elements[key].status == ElementStatus.REQUIRED}
        for key, el in list(elements.items()):
            spec = k.elements[key].zone if key in k.elements else None
            # a rival rite's element (mandap vs a requested nikah stage) stays forbidden:
            # only the generic element of that place is released
            generic = not k.elements[key].scope.traditions if key in k.elements else False
            if (el.status == ElementStatus.FORBIDDEN and el.provenance == Provenance.DETERMINISTIC_RULE
                    and spec is not None and spec.key in requested_zones and generic):
                put(key, ElementStatus.CONTEXTUAL, Provenance.USER_EXPLICIT,
                    "occupies the same place as an element the brief requested",
                    f"released by user_explicit request for the {spec.key.replace('_', ' ')}")

        # ---- descriptive semantics (knowledge first, model second, leak-checked)
        fam = k.families.get(identity.event_family or "")
        focal = (tb.focal if tb else "") or (et.focal if et else "") or (
            reading.focal_relationship if reading else "")
        profile = EventProfile(identity=identity, primary_activities=primary,
                               secondary_activities=secondary, audience_relationship=audience,
                               elements=sorted(elements.values(), key=lambda e: e.key))
        clean = _Cleaner(k, profile, overridden)

        atmosphere = _uniq(list(et.atmosphere if et else ()) + g["atmosphere"]
                           + (clean(reading.atmosphere, "atmosphere") if reading else []))
        participants = _uniq(list(fam.participants if fam else ())
                             + (clean(reading.participants, "participants") if reading else []))
        cultural = _uniq(list(fam.cultural_context if fam else ())
                         + ([f"set in {brief.location}"] if brief.location else [])
                         + (clean(reading.cultural_context, "cultural context") if reading else []))
        relationships = _uniq(list(et.relationships if et else ())
                              + [r for i in primary + secondary if i.key in k.activities
                                 for r in k.activities[i.key].relationships])
        operational = _uniq(list(et.operational if et else ())
                            + [o for i in primary + secondary if i.key in k.activities
                               for o in k.activities[i.key].operational]
                            + (clean(reading.operational_needs, "operational needs") if reading else []))
        must = _uniq(list(tb.must_communicate if tb else ()) + list(et.must_communicate if et else ())
                     + (clean(reading.must_communicate, "must communicate") if reading else []))
        if not must:
            must = _uniq([k.activities[i.key].human_activity for i in primary
                          if i.key in k.activities and k.activities[i.key].human_activity])
        visual = _uniq(list(et.visual_priorities if et else ())
                       + (clean(reading.visual_priorities, "visual priorities") if reading else []))
        if reading and not focal:
            proposed = clean([reading.focal_relationship], "focal relationship")
            focal = proposed[0] if proposed else ""
        profile = profile.model_copy(update=dict(
            participants=participants, focal_relationship=focal or "", atmosphere=atmosphere,
            operational_needs=operational, cultural_context=cultural,
            relationships=relationships, recognisability_cues=must))

        # ---- programme
        llm_zones: list[ProgramZone] = []
        if reading:
            existing = _zone_stems_for(k, profile)
            for zp in reading.zones:
                if len(llm_zones) >= MAX_MODEL_ZONES:
                    overridden.append(f"zone '{zp.key}' rejected: model zone cap ({MAX_MODEL_ZONES}) reached")
                    break
                key = slugify(zp.key or zp.label)
                stems = _stems(f"{zp.key} {zp.label}")
                if stems and stems & existing:
                    overridden.append(f"zone '{key}' rejected: duplicates an existing zone "
                                      f"({', '.join(sorted(stems & existing))})")
                    continue
                existing |= stems
                role = zp.role if zp.role in ZONE_ROLES else "social"
                leaks = find_leaks(k, profile, f"{zp.key.replace('_', ' ')} {zp.label}", "zone")
                if leaks:
                    overridden.append(f"zone '{key}' rejected: {leaks[0].describe()}")
                    continue
                prio = zp.priority if zp.priority in ("required", "recommended", "optional") else "recommended"
                if et and prio == "required":
                    prio = "recommended"
                llm_zones.append(ProgramZone(key=key, label=zp.label or key.replace("_", " ").title(),
                                             role=role, priority=prio, area_share=0.06,
                                             provenance=Provenance.LLM_INFERENCE,
                                             rationale=zp.rationale or "proposed by the reasoning model",
                                             confidence=0.6))
        programme = infer_programme(k, profile, capacity=capacity,
                                    explicit_activities=set(g["explicit_acts"]), llm_zones=llm_zones)

        # ---- invariants and rites
        invariants: list[SemanticInvariant] = []
        seen_inv: set[str] = set()

        def inv(i, prov: Provenance, why: str) -> None:
            if i.id in seen_inv:
                return
            seen_inv.add(i.id)
            invariants.append(SemanticInvariant(id=i.id, statement=i.statement, category=i.category,
                                                sacred=i.sacred, provenance=prov, rationale=why))
        if et:
            for i in et.invariants:
                inv(i, Provenance.DOMAIN_KNOWLEDGE, f"required of a {et.label}")
        if tb:
            for i in tb.invariants:
                inv(i, Provenance.DOMAIN_KNOWLEDGE, f"required by the {tb.label} rite")
        zone_acts = {z.activity for z in programme if z.priority == "required" and z.activity}
        for i_item in primary + secondary:
            act = k.activities.get(i_item.key)
            if act and act.key in zone_acts:
                for i in act.invariants:
                    inv(i, i_item.provenance, f"required by {act.label.lower()}")
        ritual_refs = list(tb.ritual_refs if tb else (et.ritual_refs if et else ()))

        # ---- intent
        pz = _primary_zone(k, programme, profile, et, tb)
        near = [e.label for e in profile.elements if e.status == ElementStatus.FORBIDDEN
                and "neighbouring" in e.rationale]
        near += [e.label for e in profile.elements if e.status == ElementStatus.FORBIDDEN
                 and e.provenance == Provenance.USER_EXPLICIT]
        # `avoid` is a list of prohibitions, so naming a forbidden element there is the
        # point, not a leak; it is length-limited but not leak-checked
        model_avoid = [" ".join(str(s).split())[:160] for s in (reading.avoid if reading else []) if s]
        avoid = _uniq(near + model_avoid)[:24]
        if identity.tradition is None and et and et.traditions:
            uncertain.append("tradition not stated: no rite-specific elements were assumed")
        intent = DesignIntent(
            primary_activity=primary[0].label if primary else "",
            primary_focus=pz.label if pz else "", primary_zone_key=pz.key if pz else "",
            experience_goals=atmosphere[:6], visual_priorities=visual[:8],
            must_communicate=must[:6], avoid=avoid,
            uncertainties=_uniq(uncertain + (reading.uncertainties if reading else []))[:8])

        return SemanticBrief(
            raw_text=brief.raw_text, profile=profile, intent=intent, programme=programme,
            capacity=capacity, location=brief.location,
            hard_constraints=[i.statement for i in invariants],
            soft_constraints=[f"atmosphere: {', '.join(atmosphere[:5])}"] if atmosphere else [],
            explicit_requests=g["requested"], invariants=invariants, ritual_refs=ritual_refs,
            space_typology=(et.typology if et else _typology_for_unknown(brief, audience, primary)),
            reasoner=trace.model_copy(update={"overridden": overridden}))


# Where attention goes decides which zone is the focus when the knowledge base cannot
# say: an immersive event centres on its medium, a convivial one on its tables.
FOCUS_ROLES_BY_AUDIENCE = {
    "immersive": ("focal", "performance", "participation"),
    "surround": ("performance", "ceremony", "focal"),
    "frontal": ("performance", "ceremony", "focal"),
    "processional": ("ceremony", "performance", "focal"),
    "participatory": ("participation", "performance", "focal"),
    "distributed": ("display", "focal", "retail", "participation"),
    "convivial": ("dining", "hospitality", "social", "focal"),
    "none": ("focal", "performance", "ceremony", "display", "dining", "social"),
}


def _primary_zone(k: Knowledge, programme, profile: EventProfile, et, tb):
    """The zone the concept is organised around.

    Known events state it: their first required element that is a place (a rite's
    before its event's). Otherwise the audience relationship decides.
    """
    by_key = {z.key: z for z in programme}
    for block in ([tb.elements["required"]] if tb else []) + ([et.elements["required"]] if et else []):
        for key in block:
            spec = k.elements[key].zone if key in k.elements else None
            if spec and spec.key in by_key:
                return by_key[spec.key]
    for role in FOCUS_ROLES_BY_AUDIENCE.get(profile.audience_relationship, ()):
        z = next((z for z in programme if z.priority == "required" and z.role == role), None)
        if z:
            return z
    return max(programme, key=lambda z: z.area_share, default=None)


MAX_MODEL_ZONES = 4
# words that describe any zone and so cannot tell two zones apart
_GENERIC_ZONE_WORDS = {"zone", "zones", "area", "areas", "space", "spaces", "position",
                       "field", "station", "stations", "point", "corner", "room", "main",
                       "the", "and", "for", "of", "with", "guest", "guests", "general"}


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower().replace("_", " "))
    return {w[:6] for w in words if w not in _GENERIC_ZONE_WORDS and len(w) > 2}


def _zone_stems_for(k: Knowledge, profile: EventProfile) -> set[str]:
    """Stems of every zone the activities and elements already imply."""
    out: set[str] = set()
    for item in profile.primary_activities + profile.secondary_activities:
        act = k.activities.get(item.key)
        for spec in (act.zones if act else ()):
            out |= _stems(f"{spec.key} {spec.label}")
        out |= _stems(item.key)
    for e in profile.elements:
        el = k.elements.get(e.key)
        if el and el.zone and e.status != ElementStatus.FORBIDDEN:
            out |= _stems(f"{el.zone.key} {el.zone.label}")
    return out


def _known_family(k: Knowledge, raw: str) -> str | None:
    """A model may answer with several families run together. Take the first known one."""
    slug = slugify(raw)
    if slug in k.families:
        return slug
    hits = sorted((slug.find(f), f) for f in k.families if f in slug)
    return hits[0][1] if hits else None


class _Cleaner:
    """Model-proposed strings pass only if they mention nothing forbidden."""

    def __init__(self, k: Knowledge, profile: EventProfile, overridden: list[str]) -> None:
        self.k, self.profile, self.overridden = k, profile, overridden

    def __call__(self, items: list[str], where: str) -> list[str]:
        out = []
        for s in items or []:
            s = " ".join(str(s).split())[:160]
            if not s:
                continue
            leaks = find_leaks(self.k, self.profile, s, where)
            if leaks:
                self.overridden.append(f"{where} '{s[:60]}' rejected: {leaks[0].describe()}")
                continue
            out.append(s)
        return out


def _uniq(items) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _venue(brief: DesignBrief) -> str | None:
    if brief.venue_text:
        return slugify(brief.venue_text)
    v = brief.venue_type.value if brief.venue_type else "UNSPECIFIED"
    return None if v == "UNSPECIFIED" else v.lower()


def _unknown_label(text: str) -> str:
    """The brief's own name for the thing: its first noun phrase, before the particulars."""
    t = " ".join((text or "").split())
    head = re.split(r"\s+(?:for|with|in|at|on|that|which|where)\s+|[,.;:]", t, maxsplit=1)[0]
    head = re.sub(r"^(?:create|design|make|build|plan|we need|i want|imagine)\s+", "", head, flags=re.I)
    head = re.sub(r"\b\d[\d,]*[-\s]*(?:person|people|guest|guests|pax|seat|seater)s?\b", "", head, flags=re.I)
    head = _LEAD.sub("", head.strip().lower()).strip(" -")
    return head[:80] if head else "unspecified brief"


def _typology_for_unknown(brief: DesignBrief, audience: str, primary) -> str:
    """Only the space-form prior. The event's meaning is already in the profile."""
    if brief.typology != Typology.GENERIC_SPATIAL:
        return brief.typology.value
    keys = {i.key for i in primary}
    if keys & {"performance", "presentation", "narration", "runway", "reveal"}:
        return "EVENT_STAGE"
    if keys & {"display", "product_display"}:
        return "EXHIBITION"
    if keys & {"dining"}:
        return "RESTAURANT"
    if keys & {"shelter"}:
        return "PAVILION"
    return "GENERIC_SPATIAL"


def log_reading(sb: SemanticBrief) -> None:
    """The semantic trace, printed as a block the way stage details are."""
    try:
        p, i = sb.profile, sb.profile.identity
        elog.note("")
        elog.note("SEMANTIC INTERPRETATION")
        elog.note(f"     raw brief   : {sb.raw_text[:110]!r}")
        elog.note(f"     reasoner    : {sb.reasoner.source}"
                  + (f" model={sb.reasoner.model} {sb.reasoner.latency_ms}ms "
                     f"attempts={sb.reasoner.attempts}" if sb.reasoner.model else "")
                  + (f" error={sb.reasoner.error}" if sb.reasoner.error else ""))
        elog.note(f"     event       : {i.event_type_label} [{i.event_type}] "
                  f"family={i.event_family} domain={i.domain} tradition={i.tradition} "
                  f"known={i.known_type} ({i.provenance.value})")
        elog.note(f"     activities  : " + ", ".join(f"{a.key}({a.provenance.value[:4]})"
                                                     for a in p.primary_activities)
                  + " | " + ", ".join(a.key for a in p.secondary_activities))
        elog.note(f"     audience    : {p.audience_relationship} — {p.focal_relationship[:80]}")
        elog.note("     PROGRAMME")
        for z in sb.programme:
            elog.note(f"       {z.priority[:3]} {z.role:<13} {z.key:<22} area={z.area_share:.3f} "
                      f"cap={z.capacity_share:.2f}  {z.provenance.value}: {z.rationale[:50]}")
        for status in (ElementStatus.REQUIRED, ElementStatus.RECOMMENDED, ElementStatus.OPTIONAL,
                       ElementStatus.CONTEXTUAL):
            items = p.with_status(status)
            if items:
                elog.note(f"     {status.value.lower():<11} : " + ", ".join(
                    f"{e.key}({e.provenance.value[:4]})" for e in items))
        forb = p.with_status(ElementStatus.FORBIDDEN)
        if forb:
            elog.note(f"     forbidden   : {len(forb)} — near-miss: " + ", ".join(
                e.key for e in forb if "neighbouring" in e.rationale
                or e.provenance == Provenance.USER_EXPLICIT))
        elog.note(f"     invariants  : " + ", ".join(
            f"{v.id}{'*' if v.sacred else ''}" for v in sb.invariants))
        elog.note(f"     intent      : focus={sb.intent.primary_focus!r} "
                  f"communicate={sb.intent.must_communicate[:2]}")
        for u in sb.intent.uncertainties[:3]:
            elog.warn(f"     uncertain   : {u}")
        for o in sb.reasoner.overridden[:6]:
            elog.warn(f"     overridden  : {o}")
    except Exception as exc:                       # pragma: no cover
        elog.warn(f"semantic logging failed ({type(exc).__name__}) — run unaffected")
