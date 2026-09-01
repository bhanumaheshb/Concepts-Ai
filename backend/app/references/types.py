"""Reference types are not interchangeable (spec §2).

Each type declares which dimensions are load-bearing (the analysis has failed without
them), secondary, and usually-absent (a trait there gets its salience capped, because
it is almost always the analyser inventing a plausible sentence to fill the schema).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.reference import ReferenceDimension as D
from app.domain.reference import ReferenceType as T

MIN_LOAD_BEARING_COVERED = 3
LOAD_BEARING_SALIENCE = 0.6
ABSENT_SALIENCE_CAP = 0.4


@dataclass(frozen=True)
class TypeProfile:
    kind: T
    load_bearing: frozenset[D]
    secondary: frozenset[D]
    usually_absent: frozenset[D]
    note: str = ""

    def cap_for(self, dimension: D) -> float:
        return ABSENT_SALIENCE_CAP if dimension in self.usually_absent else 1.0


def _p(kind, load, sec, absent, note="") -> TypeProfile:
    return TypeProfile(kind, frozenset(load), frozenset(sec), frozenset(absent), note)


PROFILES: dict[T, TypeProfile] = {
    T.MOVIE: _p(
        T.MOVIE,
        [D.ATMOSPHERE, D.EMOTIONAL_TONE, D.NARRATIVE_STRUCTURE, D.LIGHTING_PHILOSOPHY,
         D.COLOUR_BEHAVIOUR, D.SOCIAL_BEHAVIOUR, D.ERA],
        [D.SPATIAL_LANGUAGE, D.RHYTHM_PACING, D.MATERIAL_BEHAVIOUR, D.RECURRING_MOTIF],
        [D.GEOMETRY, D.SCALE],
        "production design rarely commits to a consistent geometry",
    ),
    T.TV_SERIES: _p(
        T.TV_SERIES,
        [D.ATMOSPHERE, D.EMOTIONAL_TONE, D.NARRATIVE_STRUCTURE, D.LIGHTING_PHILOSOPHY,
         D.COLOUR_BEHAVIOUR, D.SOCIAL_BEHAVIOUR, D.ERA],
        [D.SPATIAL_LANGUAGE, D.RHYTHM_PACING, D.MATERIAL_BEHAVIOUR, D.RECURRING_MOTIF,
         D.ENVIRONMENTAL_RELATIONSHIP],
        [D.GEOMETRY, D.SCALE],
        "same as film: a series has an atmosphere, not a geometry",
    ),
    T.GAME: _p(
        T.GAME,
        [D.CIRCULATION_MOVEMENT, D.ENVIRONMENTAL_RELATIONSHIP, D.RHYTHM_PACING,
         D.ATMOSPHERE, D.RECURRING_MOTIF],
        [D.NARRATIVE_STRUCTURE, D.TECHNOLOGICAL_CHARACTER, D.COLOUR_BEHAVIOUR, D.SCALE],
        [D.MATERIAL_BEHAVIOUR],
        "game surfaces are texture, not tectonics",
    ),
    T.ARCHITECTURE: _p(
        T.ARCHITECTURE,
        [D.GEOMETRY, D.ARCHITECTURAL_LANGUAGE, D.SCALE, D.CIRCULATION_MOVEMENT,
         D.MATERIAL_BEHAVIOUR, D.ENVIRONMENTAL_RELATIONSHIP],
        [D.LIGHTING_PHILOSOPHY, D.RHYTHM_PACING, D.ERA, D.TEXTURE, D.SPATIAL_LANGUAGE],
        [D.NARRATIVE_STRUCTURE, D.SOCIAL_BEHAVIOUR],
        "inferring narrative from a building is usually the analyser inventing",
    ),
    T.ART: _p(
        T.ART,
        [D.COLOUR_BEHAVIOUR, D.RHYTHM_PACING, D.RECURRING_MOTIF, D.EMOTIONAL_TONE, D.TEXTURE],
        [D.GEOMETRY, D.SCALE, D.ATMOSPHERE, D.SPATIAL_LANGUAGE],
        [D.CIRCULATION_MOVEMENT, D.ENVIRONMENTAL_RELATIONSHIP],
    ),
    T.PHOTOGRAPHY: _p(
        T.PHOTOGRAPHY,
        [D.LIGHTING_PHILOSOPHY, D.COLOUR_BEHAVIOUR, D.ATMOSPHERE, D.SCALE],
        [D.TEXTURE, D.EMOTIONAL_TONE, D.RECURRING_MOTIF],
        [D.GEOMETRY, D.NARRATIVE_STRUCTURE, D.MATERIAL_BEHAVIOUR],
    ),
    T.HISTORICAL_PERIOD: _p(
        T.HISTORICAL_PERIOD,
        [D.ERA, D.CULTURAL_CONTEXT, D.SOCIAL_BEHAVIOUR, D.ARCHITECTURAL_LANGUAGE,
         D.MATERIAL_BEHAVIOUR, D.TECHNOLOGICAL_CHARACTER],
        [D.GEOMETRY, D.COLOUR_BEHAVIOUR, D.RHYTHM_PACING, D.SCALE, D.TEXTURE],
        [],
    ),
    T.CULTURAL_REFERENCE: _p(
        T.CULTURAL_REFERENCE,
        [D.SOCIAL_BEHAVIOUR, D.NARRATIVE_STRUCTURE, D.CULTURAL_CONTEXT,
         D.RECURRING_MOTIF, D.SENSORY_ASSOCIATION],
        [D.RHYTHM_PACING, D.COLOUR_BEHAVIOUR, D.ATMOSPHERE, D.ERA],
        [D.GEOMETRY, D.MATERIAL_BEHAVIOUR],
    ),
    T.FASHION: _p(
        T.FASHION,
        [D.TEXTURE, D.MATERIAL_BEHAVIOUR, D.COLOUR_BEHAVIOUR, D.RHYTHM_PACING, D.ERA],
        [D.SCALE, D.RECURRING_MOTIF, D.EMOTIONAL_TONE],
        [D.CIRCULATION_MOVEMENT, D.ENVIRONMENTAL_RELATIONSHIP],
    ),
    T.NATURE: _p(
        T.NATURE,
        [D.GEOMETRY, D.RHYTHM_PACING, D.ENVIRONMENTAL_RELATIONSHIP,
         D.MATERIAL_BEHAVIOUR, D.SCALE],
        [D.COLOUR_BEHAVIOUR, D.TEXTURE, D.SENSORY_ASSOCIATION, D.ATMOSPHERE],
        [D.NARRATIVE_STRUCTURE, D.CULTURAL_CONTEXT, D.ERA],
        "morphology and growth, not story",
    ),
    T.TECHNOLOGY: _p(
        T.TECHNOLOGY,
        [D.TECHNOLOGICAL_CHARACTER, D.GEOMETRY, D.RHYTHM_PACING,
         D.MATERIAL_BEHAVIOUR, D.CIRCULATION_MOVEMENT],
        [D.SCALE, D.LIGHTING_PHILOSOPHY, D.TEXTURE, D.ATMOSPHERE],
        [D.ERA, D.SOCIAL_BEHAVIOUR, D.CULTURAL_CONTEXT],
    ),
    T.OTHER: _p(T.OTHER, [], list(D), [], "nothing enforced"),
}

# dimension -> the genotype facets it may legitimately bias
DIMENSION_FACETS: dict[D, tuple[str, ...]] = {
    D.SPATIAL_LANGUAGE: ("geometry_system", "occupation_staging", "thesis_archetype"),
    D.ARCHITECTURAL_LANGUAGE: ("architectural_language", "tectonic_logic"),
    D.GEOMETRY: ("geometry_system", "structural_logic"),
    D.SCALE: ("scale_strategy",),
    D.CIRCULATION_MOVEMENT: ("spatial_narrative", "occupation_staging"),
    D.ENVIRONMENTAL_RELATIONSHIP: ("site_relationship", "scale_strategy"),
    D.MATERIAL_BEHAVIOUR: ("material_palette", "tectonic_logic"),
    D.TEXTURE: ("material_palette", "tectonic_logic"),
    D.COLOUR_BEHAVIOUR: ("material_palette", "lighting_philosophy"),
    D.LIGHTING_PHILOSOPHY: ("lighting_philosophy",),
    D.ATMOSPHERE: ("emotional_register", "lighting_philosophy"),
    D.EMOTIONAL_TONE: ("emotional_register",),
    D.SENSORY_ASSOCIATION: ("material_palette", "lighting_philosophy"),
    D.RHYTHM_PACING: ("geometry_system", "spatial_narrative"),
    D.NARRATIVE_STRUCTURE: ("spatial_narrative", "thesis_archetype"),
    D.SOCIAL_BEHAVIOUR: ("occupation_staging", "emotional_register"),
    D.RECURRING_MOTIF: ("geometry_system", "tectonic_logic"),
    # CONTEXT dimensions map to nothing by construction
    D.ERA: (),
    D.CULTURAL_CONTEXT: (),
    D.TECHNOLOGICAL_CHARACTER: (),
}


def profile(kind) -> TypeProfile:
    return PROFILES[kind]


def coverage_ok(kind, traits) -> tuple[bool, list[str]]:
    """R-REF-05: >= 3 load-bearing dimensions at salience >= 0.6."""
    prof = PROFILES[kind]
    if not prof.load_bearing:
        return True, []
    covered = {
        t.dimension for t in traits
        if t.dimension in prof.load_bearing and t.salience >= LOAD_BEARING_SALIENCE
    }
    if len(covered) >= MIN_LOAD_BEARING_COVERED:
        return True, sorted(d.value for d in covered)
    missing = sorted(d.value for d in prof.load_bearing - covered)
    return False, missing


def cap_salience(kind, traits: list) -> list:
    """Traits on a type's usually-absent dimensions get their salience capped."""
    prof = PROFILES[kind]
    out = []
    for t in traits:
        cap = prof.cap_for(t.dimension)
        out.append(t.model_copy(update={"salience": min(t.salience, cap)}) if t.salience > cap else t)
    return out


def facets_for(dimension) -> tuple[str, ...]:
    return DIMENSION_FACETS.get(dimension, ())
