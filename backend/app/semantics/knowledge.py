"""The semantic knowledge base, and the phrase matcher that reads briefs against it.

Everything domain-specific lives in `knowledge/<version>/*.yaml`. This module knows
the SHAPE of that knowledge — events, families, activities, elements, scopes — and
nothing about any particular event. A new event type, activity or ritual element is
a data change; nothing here is edited to support it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent / "knowledge"

# Words that turn a mention into an exclusion when they closely precede it:
# "no bar", "without a mandap", "we don't want a stage".
_NEGATORS = ("no", "not", "without", "avoid", "avoiding", "exclude", "excluding", "never",
             "minus", "don't", "dont", "nor", "skip", "instead of", "rather than")
_NEGATION_WINDOW = 4   # words


def normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", " ")
    return " ".join(t.split())


@dataclass(frozen=True)
class Match:
    key: str
    phrase: str
    start: int
    end: int
    negated: bool = False


class PhraseIndex:
    """Word-bounded, longest-match-first, non-overlapping phrase matching.

    Longest-first is what keeps "fire altar" from also being read as an "altar", and
    "haldi ceremony" from also being read as a "ceremony". Consumed spans are masked,
    so one stretch of text is attributed to exactly one meaning.
    """

    def __init__(self, entries: dict[str, list[str]]) -> None:
        pairs: list[tuple[str, str]] = []
        for key, phrases in entries.items():
            for p in phrases:
                p = normalise(p)
                if p:
                    pairs.append((p, key))
        # longest phrase first; stable on key for determinism
        pairs.sort(key=lambda t: (-len(t[0]), t[0], t[1]))
        self._compiled = [
            (re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])"), p, k)
            for p, k in pairs
        ]

    def find(self, text: str, masked: list[tuple[int, int]] | None = None) -> list[Match]:
        t = normalise(text)
        taken: list[tuple[int, int]] = list(masked or [])
        out: list[Match] = []
        for rx, phrase, key in self._compiled:
            for m in rx.finditer(t):
                s, e = m.span()
                if any(s < te and e > ts for ts, te in taken):
                    continue
                taken.append((s, e))
                out.append(Match(key=key, phrase=phrase, start=s, end=e,
                                 negated=_is_negated(t, s)))
        out.sort(key=lambda m: m.start)
        return out


def _is_negated(text: str, start: int) -> bool:
    window = " ".join(text[:start].split()[-_NEGATION_WINDOW:])
    # a sentence break inside the window ends the negation's reach
    window = re.split(r"[.;:!?]", window)[-1]
    return any(re.search(r"(?<![a-z'])" + re.escape(n) + r"(?![a-z'])", window)
               for n in _NEGATORS)


# ─────────────────────────────── records ───────────────────────────────

@dataclass(frozen=True)
class ZoneSpec:
    key: str
    label: str
    role: str
    priority: str = "required"
    area_share: float = 0.1
    capacity_share: float = 0.0


@dataclass(frozen=True)
class Invariant:
    id: str
    statement: str
    category: str = "PROGRAM"
    sacred: bool = False


@dataclass(frozen=True)
class Scope:
    event_types: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    traditions: tuple[str, ...] = ()

    @property
    def is_neutral(self) -> bool:
        return not (self.event_types or self.families or self.traditions)


@dataclass(frozen=True)
class Element:
    key: str
    label: str
    aliases: tuple[str, ...]
    zone: ZoneSpec | None
    scope: Scope
    physical: bool = True


@dataclass(frozen=True)
class Activity:
    key: str
    label: str
    cues: tuple[str, ...]
    audience: str
    zones: tuple[ZoneSpec, ...]
    relationships: tuple[str, ...]
    human_activity: str
    time_of_day: str
    invariants: tuple[Invariant, ...]
    operational: tuple[str, ...]


@dataclass(frozen=True)
class TraditionBlock:
    key: str
    label: str
    focal: str
    elements: dict[str, tuple[str, ...]]
    ritual_refs: tuple[str, ...]
    must_communicate: tuple[str, ...]
    invariants: tuple[Invariant, ...]


@dataclass(frozen=True)
class EventType:
    key: str
    label: str
    family: str
    domain: str
    aliases: tuple[str, ...]
    family_aliases: tuple[str, ...]
    typology: str
    primary_activities: tuple[str, ...]
    secondary_activities: tuple[str, ...]
    suppress_activities: tuple[str, ...]
    audience: str
    focal: str
    atmosphere: tuple[str, ...]
    elements: dict[str, tuple[str, ...]]
    zones: tuple[ZoneSpec, ...]
    visual_priorities: tuple[str, ...]
    must_communicate: tuple[str, ...]
    relationships: tuple[str, ...]
    operational: tuple[str, ...]
    invariants: tuple[Invariant, ...]
    ritual_refs: tuple[str, ...]
    traditions: dict[str, TraditionBlock] = field(default_factory=dict)
    proper_name: bool = False        # "Sangeet" stays capitalised; "product launch" does not


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    domain: str
    cultural_context: tuple[str, ...]
    participants: tuple[str, ...]


@dataclass(frozen=True)
class Tradition:
    key: str
    label: str
    cues: tuple[str, ...]


# ─────────────────────────────── loading ───────────────────────────────

def _t(v) -> tuple:
    return tuple(v or ())


def _zone(d: dict, default_priority: str = "required") -> ZoneSpec:
    return ZoneSpec(key=d["key"], label=d.get("label", d["key"].replace("_", " ").title()),
                    role=d.get("role", "social"), priority=d.get("priority", default_priority),
                    area_share=float(d.get("area_share", 0.1)),
                    capacity_share=float(d.get("capacity_share", 0.0)))


def _inv(d: dict) -> Invariant:
    return Invariant(id=d["id"], statement=d["statement"], category=d.get("category", "PROGRAM"),
                     sacred=bool(d.get("sacred", False)))


def _elements_block(d: dict | None) -> dict[str, tuple[str, ...]]:
    d = d or {}
    return {k: _t(d.get(k)) for k in ("required", "recommended", "optional")}


class Knowledge:
    def __init__(self, version: str = "v1") -> None:
        base = ROOT / version
        self.version = version
        ev = yaml.safe_load((base / "events.yaml").read_text(encoding="utf-8"))
        ac = yaml.safe_load((base / "activities.yaml").read_text(encoding="utf-8"))
        el = yaml.safe_load((base / "elements.yaml").read_text(encoding="utf-8"))
        sp_path = base / "spaces.yaml"
        sp = yaml.safe_load(sp_path.read_text(encoding="utf-8")) if sp_path.exists() else {}
        # what each space type narrows in the form: suggested families and venues
        self.spaces: dict[str, dict] = sp.get("spaces") or {}
        self.venues: dict[str, str] = sp.get("venues") or {}

        self.families: dict[str, Family] = {
            k: Family(key=k, label=v.get("label", k), domain=v.get("domain", "event"),
                      cultural_context=_t(v.get("cultural_context")),
                      participants=_t(v.get("participants")))
            for k, v in (ev.get("families") or {}).items()
        }
        self.traditions: dict[str, Tradition] = {
            k: Tradition(key=k, label=v.get("label", k), cues=_t(v.get("cues")))
            for k, v in (ev.get("traditions") or {}).items()
        }
        self.activities: dict[str, Activity] = {
            k: Activity(key=k, label=v.get("label", k), cues=_t(v.get("cues")),
                        audience=v.get("audience", "none"),
                        zones=tuple(_zone(z) for z in v.get("zones") or []),
                        relationships=_t(v.get("relationships")),
                        human_activity=v.get("human_activity", ""),
                        time_of_day=v.get("time_of_day", ""),
                        invariants=tuple(_inv(i) for i in v.get("invariants") or []),
                        operational=_t(v.get("operational")))
            for k, v in (ac.get("activities") or {}).items()
        }
        self.elements: dict[str, Element] = {}
        for k, v in (el.get("elements") or {}).items():
            sc = v.get("scope") or {}
            self.elements[k] = Element(
                key=k, label=v.get("label", k), aliases=_t(v.get("aliases")),
                zone=_zone(v["zone"]) if v.get("zone") else None,
                scope=Scope(event_types=_t(sc.get("event_types")),
                            families=_t(sc.get("families")),
                            traditions=_t(sc.get("traditions"))),
                physical=bool(v.get("physical", True)))
        self.event_types: dict[str, EventType] = {}
        for k, v in (ev.get("event_types") or {}).items():
            fam = v.get("family", "")
            acts = v.get("activities") or {}
            trads = {
                tk: TraditionBlock(
                    key=tk, label=tv.get("label", tk), focal=tv.get("focal", ""),
                    elements=_elements_block(tv.get("elements")),
                    ritual_refs=_t(tv.get("ritual_refs")),
                    must_communicate=_t(tv.get("must_communicate")),
                    invariants=tuple(_inv(i) for i in tv.get("invariants") or []))
                for tk, tv in (v.get("traditions") or {}).items()
            }
            self.event_types[k] = EventType(
                key=k, label=v.get("label", k.replace("_", " ").title()), family=fam,
                domain=v.get("domain") or (self.families[fam].domain if fam in self.families
                                           else "event"),
                aliases=_t(v.get("aliases")), family_aliases=_t(v.get("family_aliases")),
                typology=v.get("typology", "GENERIC_SPATIAL"),
                primary_activities=_t(acts.get("primary")),
                secondary_activities=_t(acts.get("secondary")),
                suppress_activities=_t(v.get("suppress_activities")),
                audience=v.get("audience", "none"), focal=v.get("focal", ""),
                atmosphere=_t(v.get("atmosphere")),
                elements=_elements_block(v.get("elements")),
                zones=tuple(_zone(z) for z in v.get("zones") or []),
                visual_priorities=_t(v.get("visual_priorities")),
                must_communicate=_t(v.get("must_communicate")),
                relationships=_t(v.get("relationships")),
                operational=_t(v.get("operational")),
                invariants=tuple(_inv(i) for i in v.get("invariants") or []),
                ritual_refs=_t(v.get("ritual_refs")), traditions=trads,
                proper_name=bool(v.get("proper_name", False)))
        self._validate()

        # indices
        self.event_index = PhraseIndex({k: list(e.aliases) for k, e in self.event_types.items()})
        self.family_alias_index = PhraseIndex(
            {k: list(e.family_aliases) for k, e in self.event_types.items() if e.family_aliases})
        self.activity_index = PhraseIndex({k: list(a.cues) for k, a in self.activities.items()})
        self.element_index = PhraseIndex({k: list(e.aliases) for k, e in self.elements.items()})
        self.tradition_index = PhraseIndex({k: list(t.cues) for k, t in self.traditions.items()})

    def _validate(self) -> None:
        """Referential integrity. A typo in YAML must fail loudly at load, not produce
        a silently empty programme at run time."""
        problems: list[str] = []
        for et in self.event_types.values():
            if et.family and et.family not in self.families:
                problems.append(f"event {et.key}: unknown family {et.family}")
            for a in et.primary_activities + et.secondary_activities + et.suppress_activities:
                if a not in self.activities:
                    problems.append(f"event {et.key}: unknown activity {a}")
            blocks = [et.elements] + [t.elements for t in et.traditions.values()]
            for block in blocks:
                for keys in block.values():
                    for k in keys:
                        if k not in self.elements:
                            problems.append(f"event {et.key}: unknown element {k}")
        for el in self.elements.values():
            for t in el.scope.event_types:
                if t not in self.event_types:
                    problems.append(f"element {el.key}: scope names unknown event {t}")
            for f in el.scope.families:
                if f not in self.families:
                    problems.append(f"element {el.key}: scope names unknown family {f}")
        for key, space in self.spaces.items():
            for f in space.get("families") or []:
                if f not in self.families:
                    problems.append(f"space {key}: unknown family {f}")
            for v in space.get("venues") or []:
                if v not in self.venues:
                    problems.append(f"space {key}: unknown venue {v}")
        if problems:
            raise ValueError("semantic knowledge base is inconsistent:\n  " + "\n  ".join(problems))

    # ---- lookups ------------------------------------------------------------
    def resolve_event_key(self, raw: str | None) -> str | None:
        """A UI selection or API value -> a known key, tolerant of spelling and case."""
        if not raw:
            return None
        slug = re.sub(r"[^a-z0-9]+", "_", normalise(raw)).strip("_")
        if slug in self.event_types:
            return slug
        legacy = {"sangeeth": "sangeet", "wedding": "wedding_ceremony",
                  "reception": "wedding_reception", "mehndi": "mehendi"}
        if slug in legacy:
            return legacy[slug]
        hits = self.event_index.find(raw)
        return hits[0].key if hits else None

    def family_of(self, event_key: str | None) -> str | None:
        et = self.event_types.get(event_key or "")
        return et.family if et else None


@lru_cache(maxsize=4)
def load_knowledge(version: str = "v1") -> Knowledge:
    return Knowledge(version)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalise(text)).strip("_")[:64] or "unspecified"
