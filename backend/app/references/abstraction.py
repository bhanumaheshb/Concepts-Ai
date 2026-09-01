"""REF-02 — the abstraction ladder.

STRIP → RELATE → LIFT → MAP → VERIFY.

The governing rule: a transferable principle must be understandable by a designer who
has never encountered the reference. Steps 1 and 3 are deterministic and do most of the
work; step 5 confirms rather than decides.
"""
from __future__ import annotations

import re

from app.core.ids import deterministic_id
from app.domain.common import NicheRole
from app.domain.reference import (
    AbstractionRecord, CONTEXT_DIMENSIONS, ReferenceDNA, ReferenceDimension,
    ReferenceTrait, contains_token, detect_proper_nouns,
)
from app.ontology.graph import Principle, PrincipleProvenance
from app.references.types import facets_for

RUNTIME_PREFIX = "refprin_"

# Domain nouns that name an object rather than a relation. LIFT replaces them with the
# spatial function they perform, which is what makes the statement transferable.
_OBJECT_NOUNS: dict[str, str] = {
    "ballroom": "a room whose purpose is collective display",
    "stage": "a surface that separates performer from audience",
    "chandelier": "an overhead source that declares itself",
    "corridor": "a length that delays arrival",
    "staircase": "a change of level made into a sequence",
    "throne": "a position that fixes where authority sits",
    "altar": "a point every sightline is organised around",
    "courtyard": "an outdoor room held by its own building",
    "facade": "the face a building presents before it is entered",
    "canopy": "an overhead plane that defines ground without enclosing it",
}
_VISUAL_ONLY = re.compile(
    r"\b(looks? like|appears? as|in the style of|reminiscent of|evoking|aesthetic of)\b", re.I
)


class AbstractionError(RuntimeError):
    pass


# ─────────────────────────── the five steps ───────────────────────────

def strip(statement: str, blocked: list[str]) -> tuple[str, list[str]]:
    """1 STRIP — remove blocked tokens and proper nouns."""
    removed: list[str] = []
    out = statement
    for tok in sorted(blocked, key=len, reverse=True):
        if contains_token(out, tok):
            removed.append(tok)
            out = re.sub(rf"\b{re.escape(tok)}\b\s*", "", out, flags=re.I)
    for noun in detect_proper_nouns(out):
        removed.append(noun)
        out = re.sub(rf"\b{re.escape(noun)}\b\s*", "", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;"), removed


def relates(statement: str) -> bool:
    """2 RELATE — a statement must describe a relation, not merely name an object."""
    if _VISUAL_ONLY.search(statement):
        return False
    words = statement.split()
    if len(words) < 5:
        return False
    # a relation needs a verb-ish connective; naming three nouns is not a principle
    return bool(re.search(
        r"\b(is|are|becomes?|holds?|replaces?|carries|governs?|organis\w+|reveals?|"
        r"defines?|sits?|arrives?|moves?|changes?|separates?|records?|performs?|"
        r"generat\w+|admits?|emits?|refus\w+|alternat\w+|disclos\w+|made|used|treated|"
        r"lit|worked|spaced|left|originat\w+|accumulat\w+|expressed?|read|reconfigur\w+|"
        r"respond\w*|shares?|sits?|stand\w*|encount\w+|withheld|admitted)\b",
        statement, re.I))


def lift(statement: str) -> tuple[str, bool]:
    """3 LIFT — replace domain nouns with the spatial function they perform."""
    changed = False
    out = statement
    for noun, function in _OBJECT_NOUNS.items():
        if contains_token(out, noun):
            out = re.sub(rf"\b(the |a |an )?{re.escape(noun)}s?\b", function, out, flags=re.I)
            changed = True
    return re.sub(r"\s{2,}", " ", out).strip(), changed



def build_biases(suggests, dimension, space) -> dict[str, list[str]]:
    """Group suggests by THEIR OWN facet.

    A trait on ARCHITECTURAL_LANGUAGE may legitimately suggest a geometry value; the
    earlier logic iterated `maps_to` and filtered, so any suggest whose facet was not
    first in that list was silently discarded and the principle ended up with no bias
    at all — injected, but unable to reach a genotype.
    """
    allowed = set(facets_for(dimension))
    out: dict[str, list[str]] = {}
    for s in suggests:
        prefix = s.split(":", 1)[0]
        facet = "material_palette" if prefix == "material" else prefix
        if facet not in allowed:
            continue
        if space is not None and not space.is_legal(facet, s):
            continue
        out.setdefault(facet, []).append(s)
    return {k: sorted(dict.fromkeys(v)) for k, v in sorted(out.items())}


def map_facets(trait: ReferenceTrait, space) -> list[str]:
    """4 MAP — keep only facets that are declared for the dimension AND legal here."""
    if trait.dimension in CONTEXT_DIMENSIONS:
        return []
    declared = set(facets_for(trait.dimension)) & set(trait.maps_to or facets_for(trait.dimension))
    if space is None:
        return sorted(declared)
    return sorted(f for f in declared if space.legal(f))


def verify(statement: str, dna: ReferenceDNA) -> list[str]:
    """5 VERIFY — the describability test, as a set of deterministic failures."""
    problems: list[str] = []
    if contains_token(statement, dna.identity.display_name):
        problems.append("names the reference")
    for tok in dna.surface_lexicon.blocked():
        if contains_token(statement, tok):
            problems.append(f"contains blocked token {tok!r}")
    nouns = detect_proper_nouns(statement)
    if nouns:
        problems.append(f"contains proper noun(s) {nouns}")
    if not relates(statement):
        problems.append("describes an object or a look rather than a relation")
    return problems


# ─────────────────────────── the ladder ───────────────────────────

def abstract_trait(
    trait: ReferenceTrait, dna: ReferenceDNA, space, abstraction_floor: float,
) -> tuple[str | None, AbstractionRecord]:
    steps: list[str] = []
    blocked = dna.surface_lexicon.blocked() + list(trait.surface_tokens)

    text, removed = strip(trait.statement, blocked)
    if removed:
        steps.append("STRIP")

    if not relates(text):
        steps.append("RELATE:fail")
        return None, AbstractionRecord(
            trait_id=trait.trait_id, dimension=trait.dimension, raw=trait.statement,
            lifted=text, steps_applied=steps, removed_tokens=removed)

    if trait.abstraction < abstraction_floor:
        text, changed = lift(text)
        steps.append("LIFT" if changed else "LIFT:noop")
        if not changed and trait.abstraction < abstraction_floor - 0.15:
            steps.append("DROP:below_floor")
            return None, AbstractionRecord(
                trait_id=trait.trait_id, dimension=trait.dimension, raw=trait.statement,
                lifted=text, steps_applied=steps, removed_tokens=removed)

    problems = verify(text, dna)
    steps.append("VERIFY:ok" if not problems else f"VERIFY:fail({'; '.join(problems)})")
    if problems:
        return None, AbstractionRecord(
            trait_id=trait.trait_id, dimension=trait.dimension, raw=trait.statement,
            lifted=text, steps_applied=steps, removed_tokens=removed)

    return text, AbstractionRecord(
        trait_id=trait.trait_id, dimension=trait.dimension, raw=trait.statement,
        lifted=text, steps_applied=steps, removed_tokens=removed)


def _abstract_label(dimension: ReferenceDimension, statement: str) -> str:
    """The principle's source_domain — a short readable phrase.

    Abstract by construction: it is derived from the already-abstracted statement, so
    it can never name the reference (R-REF-08). Shown in the UI and permitted to reach
    a prompt, so it has to read as English rather than as keywords.
    """
    clause = re.split(r"[;,]| rather than | so that ", statement.strip())[0].strip()
    clause = re.sub(r"^(a|an|the)\s+", "", clause, flags=re.I).strip()
    if len(clause) > 52:
        clause = clause[:52].rsplit(" ", 1)[0]
    return clause.lower() or dimension.value.lower().replace("_", " ")


def principles_from(
    dna: ReferenceDNA, space, abstraction_floor: float,
    role_eligibility: tuple[str, ...] | None = None,
) -> tuple[list[Principle], list[AbstractionRecord]]:
    """Traits → runtime Principles, carrying provenance and the dimension they came from."""
    principles: list[Principle] = []
    log: list[AbstractionRecord] = []
    blocked = dna.surface_lexicon.blocked()

    for trait in sorted(dna.traits, key=lambda t: (-t.salience, t.trait_id)):
        text, record = abstract_trait(trait, dna, space, abstraction_floor)
        log.append(record)
        if text is None:
            continue
        facets = map_facets(trait, space)
        if not facets:
            continue                       # CONTEXT dimensions and pruned-away facets
        biases = build_biases(trait.suggests, trait.dimension, space)
        facets = sorted(set(facets) | set(biases))
        pid = RUNTIME_PREFIX + deterministic_id("", dna.identity.reference_id,
                                                trait.trait_id).lstrip("_")
        principles.append(Principle(
            id=pid,
            source_domain=_abstract_label(trait.dimension, text),
            domain_class=_domain_class_for(dna),
            statements=[text],
            mappable_to=facets,
            biases=biases,
            forbidden_surface_tokens=blocked,
            cost_band_shift=0,
            provenance=PrincipleProvenance(
                source="REFERENCE",
                reference_ids=(dna.identity.reference_id,),
                derived_from_traits=(trait.trait_id,),
                abstraction=trait.abstraction,
                dimension=trait.dimension.value,
            ),
            role_eligibility=role_eligibility,
            salience=trait.salience,
        ))
    return principles, log


def _domain_class_for(dna: ReferenceDNA) -> str:
    kind = dna.identity.kind.value
    return {
        "MOVIE": "CINEMA", "TV_SERIES": "CINEMA", "GAME": "CINEMA",
        "ARCHITECTURE": "ARCHITECTURE_HISTORIC", "HISTORICAL_PERIOD": "ARCHITECTURE_HISTORIC",
        "ART": "CRAFT", "PHOTOGRAPHY": "CINEMA", "FASHION": "CRAFT",
        "CULTURAL_REFERENCE": "RITUAL", "NATURE": "NATURE", "TECHNOLOGY": "ENGINEERING",
    }.get(kind, "CRAFT")
