"""§9 — influence as a genotype constraint.

One slider, five derived constraints. Three properties hold at every level:
WILDCARD is never reached (R-REF-03), at most 3 of 12 facets are biased (R-REF-02),
and the prior multiplier only re-weights — it never prunes (R-REF-14).
"""
from __future__ import annotations

from app.domain.common import NicheRole
from app.domain.reference import (
    ReferenceDimension, ReferenceInfluence, ReferencePreset, ReferenceRequest,
)

R = NicheRole
_BANDS: list[tuple[float, float, str, int, int, float, tuple[NicheRole, ...], int, float]] = [
    # lo,   hi,   label,       facets, principles, mult, roles, literal_quota, abstraction_floor
    (0.00, 0.20, "trace",       1, 1, 1.2, (R.EXPLORATORY,),                                0, 0.85),
    (0.20, 0.45, "light",       1, 3, 1.8, (R.EXPLORATORY, R.ADJACENT),                     1, 0.75),
    (0.45, 0.70, "balanced",    2, 4, 2.6, (R.ADJACENT, R.EXPLORATORY, R.RADICAL),          1, 0.65),
    (0.70, 0.90, "strong",      2, 5, 3.0, (R.CANONICAL, R.ADJACENT, R.EXPLORATORY, R.RADICAL), 2, 0.60),
    (0.90, 1.01, "maximum",     3, 6, 4.0, (R.CANONICAL, R.ADJACENT, R.EXPLORATORY, R.RADICAL), 2, 0.55),
]

PRESETS: dict[ReferencePreset, tuple[tuple[ReferenceDimension, ...], float, float | None]] = {
    ReferencePreset.INSPIRED_BY: ((), 0.55, None),
    ReferencePreset.ERA: ((
        ReferenceDimension.ERA, ReferenceDimension.CULTURAL_CONTEXT,
        ReferenceDimension.MATERIAL_BEHAVIOUR, ReferenceDimension.ARCHITECTURAL_LANGUAGE,
        ReferenceDimension.TECHNOLOGICAL_CHARACTER), 0.70, None),
    ReferencePreset.ATMOSPHERE: ((
        ReferenceDimension.ATMOSPHERE, ReferenceDimension.EMOTIONAL_TONE,
        ReferenceDimension.LIGHTING_PHILOSOPHY, ReferenceDimension.COLOUR_BEHAVIOUR,
        ReferenceDimension.SENSORY_ASSOCIATION), 0.60, None),
    ReferencePreset.ARCHITECTURAL: ((
        ReferenceDimension.ARCHITECTURAL_LANGUAGE, ReferenceDimension.GEOMETRY,
        ReferenceDimension.SCALE, ReferenceDimension.CIRCULATION_MOVEMENT,
        ReferenceDimension.ENVIRONMENTAL_RELATIONSHIP), 0.75, None),
    ReferencePreset.NARRATIVE: ((
        ReferenceDimension.NARRATIVE_STRUCTURE, ReferenceDimension.SOCIAL_BEHAVIOUR,
        ReferenceDimension.RHYTHM_PACING, ReferenceDimension.CIRCULATION_MOVEMENT), 0.60, None),
    ReferencePreset.HYBRID: ((), 0.50, None),
    ReferencePreset.FREE_INTERPRETATION: ((), 0.30, 0.85),
}


def band_for(level: float) -> tuple:
    level = max(0.0, min(1.0, level))
    for row in _BANDS:
        if row[0] <= level < row[1]:
            return row
    return _BANDS[-1]


def derive(level: float, influence_cap: float | None = None,
           abstraction_floor_override: float | None = None) -> ReferenceInfluence:
    if influence_cap is not None:
        level = min(level, influence_cap)      # HIGH_RISK caps at 0.6
    lo, hi, label, facets, principles, mult, roles, quota, floor = band_for(level)
    return ReferenceInfluence(
        level=round(max(0.0, min(1.0, level)), 4),
        band=label,
        max_biased_facets=min(3, facets),      # R-REF-02, belt and braces
        max_principles=principles,
        prior_multiplier=mult,
        role_coverage=[r for r in roles if r is not NicheRole.WILDCARD],   # R-REF-03
        literal_quota=quota,
        abstraction_floor=(abstraction_floor_override
                           if abstraction_floor_override is not None else floor),
    )


def resolve_request(request: ReferenceRequest,
                    influence_cap: float | None = None) -> tuple[ReferenceInfluence, list]:
    """A preset writes into the request and then does not exist — nothing downstream
    branches on it (§10)."""
    dims, preset_level, floor_override = PRESETS[request.preset]
    level = request.influence if request.influence != 0.55 else preset_level
    if request.preset is ReferencePreset.INSPIRED_BY:
        level = request.influence
    dimension_filter = list(request.dimension_filter) or list(dims)
    return derive(level, influence_cap, floor_override), dimension_filter
