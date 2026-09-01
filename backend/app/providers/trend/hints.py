"""Evidence → principle hints, WITHOUT quoting the web into the creative engine.

The rule from the brief is explicit: raw article titles must not reach the creative
engine. So retrieved text is used only to DETECT which design dimensions a signal is
actually about; the statement that enters the engine is a pre-authored abstract reading
for that dimension. Every hint records the term that triggered it and the source URL.
"""
from __future__ import annotations

import re
from functools import lru_cache

from app.domain.reference import ReferenceDimension as D
from app.domain.trend import PrincipleHint, TrendEvidence

# term cluster → (dimension, abstract relational statement, ontology suggestions)
DIMENSION_CUES: list[tuple[tuple[str, ...], D, str, tuple[str, ...]]] = [
    (("light", "lighting", "daylight", "glow", "luminous", "shadow", "lit"),
     D.LIGHTING_PHILOSOPHY,
     "light is shaped as a material with edges rather than set as a level",
     ("lighting_philosophy:sculpted_shadow",)),
    (("material", "materials", "timber", "wood", "stone", "clay", "terracotta",
      "concrete", "steel", "brass", "patina", "raw"),
     D.MATERIAL_BEHAVIOUR,
     "the material is left legible as itself instead of finished into a surface",
     ("tectonic_logic:mass_bearing",)),
    (("texture", "tactile", "touch", "textile", "fabric", "woven", "surface", "finish"),
     D.TEXTURE,
     "the surface within reach carries more information than the surface at distance",
     ()),
    (("sustainab", "circular", "reuse", "reclaim", "disassembly", "carbon", "waste"),
     D.ENVIRONMENTAL_RELATIONSHIP,
     "the assembly is designed to be taken apart, so nothing is finally attached",
     ("tectonic_logic:demountable_frame",)),
    (("biophilic", "nature", "planting", "green", "garden", "landscape", "organic"),
     D.ENVIRONMENTAL_RELATIONSHIP,
     "the living element sets the terms and the built element accommodates it",
     ()),
    (("modular", "flexible", "adaptable", "reconfigur", "multi-use", "transform"),
     D.GEOMETRY,
     "one rule of assembly is repeated at several sizes rather than one fixed form",
     ("geometry_system:modular_aggregation",)),
    (("immersive", "sensory", "atmosphere", "ambient", "mood", "scent", "sound",
      "acoustic", "multisensory"),
     D.ATMOSPHERE,
     "the room is understood through more than one sense before it is understood by sight",
     ()),
    (("intimate", "intimacy", "human scale", "cosy", "cozy", "smaller", "micro"),
     D.SCALE,
     "the large gathering is composed as a set of small ones that can see each other",
     ("scale_strategy:intimate_pocket",)),
    (("monumental", "grand", "dramatic", "statement", "sculptural", "bold"),
     D.SCALE,
     "one element is oversized so that everything else can be read against it",
     ()),
    (("journey", "flow", "circulation", "route", "wayfinding", "threshold", "arrival",
      "sequence", "reveal"),
     D.CIRCULATION_MOVEMENT,
     "the route withholds the whole until the visitor has committed to the path",
     ("spatial_narrative:sequential_reveal",)),
    (("community", "gather", "social", "communal", "shared", "connection", "together"),
     D.SOCIAL_BEHAVIOUR,
     "the crowd is composed as deliberately as the room is",
     ()),
    (("craft", "artisan", "handmade", "heritage", "traditional", "local", "vernacular"),
     D.CULTURAL_CONTEXT,
     "the making is left visible so the labour is part of what is read",
     ()),
    (("colour", "color", "palette", "saturated", "tonal", "hue", "chromatic"),
     D.COLOUR_BEHAVIOUR,
     "colour is used to separate zones rather than to decorate them",
     ()),
    (("technology", "digital", "ai", "projection", "interactive", "responsive",
      "sensor"),
     D.TECHNOLOGICAL_CHARACTER,
     "the system's operation is made legible while it runs rather than concealed",
     ()),
    (("silhouette", "drape", "structured shoulders", "volume", "proportion", "line"),
     D.GEOMETRY,
     "the outline is built from a structure that the eye can reconstruct",
     ()),
]

MAX_HINTS = 5


@lru_cache(maxsize=256)
def _cue_pattern(cue: str) -> re.Pattern[str]:
    """A cue is a word stem, matched at a word boundary — never a bare substring.
    ('ai' must not fire on "chair"; 'lit' must not fire on "quality".)"""
    return re.compile(rf"\b{re.escape(cue)}\b" if len(cue) <= 4
                      else rf"\b{re.escape(cue)}", re.I)


def _fires(cue: str, text: str) -> int:
    return len(_cue_pattern(cue).findall(text))


def hints_from_evidence(evidence: list[TrendEvidence]) -> list[PrincipleHint]:
    """Detect dimensions; emit authored statements. No retrieved sentence is copied."""
    text = " ".join(f"{e.title} {e.excerpt}" for e in evidence).lower()
    scored: list[tuple[int, PrincipleHint]] = []
    seen: set[D] = set()
    for cues, dim, statement, suggests in DIMENSION_CUES:
        hits = [c for c in cues if _fires(c, text)]
        if not hits or dim in seen:
            continue
        source = next((e.url or e.publisher for e in evidence
                       if any(_fires(c, f"{e.title} {e.excerpt}") for c in hits)), "")
        seen.add(dim)
        scored.append((sum(_fires(c, text) for c in hits), PrincipleHint(
            dimension=dim, statement=statement,
            abstraction=0.86,
            # derived, not authored: salience stays below a curated hint's
            salience=0.58,
            suggests=list(suggests),
            evidence_note=f"cue '{hits[0]}' observed in retrieved evidence"
                          + (f" ({source})" if source else ""),
        )))
    scored.sort(key=lambda kv: (-kv[0], kv[1].dimension.value))
    return [h for _, h in scored[:MAX_HINTS]]
