"""CuratedReferenceAnalyzer — the V1 implementation.

Fixture lookup with alias matching, plus a deterministic fallback analyser for
unresolved queries that still produces a schema-valid, ontology-grounded DNA.

Never invents an ontology ref (R-REF-19). Never lets the display name reach a trait
statement (R-REF-06 / R-REF-07) — the domain validators enforce that on construction.
"""
from __future__ import annotations

import difflib
import re

from app.core.ids import deterministic_id
from app.core.seeded import SeededRandom
from app.domain.reference import (
    DimensionCoverage, LiteralReading, ReferenceDNA, ReferenceDimension as D,
    ReferenceIdentity, ReferenceTrait, ReferenceType as T, SurfaceLexicon, SurfaceToken,
    detect_proper_nouns,
)
from app.ontology.graph import Ontology
from app.references.fixtures import all_fixtures
from app.references.types import profile

MATCH_THRESHOLD = 0.72

# Generic, ontology-grounded traits used when a query resolves to nothing curated.
# Deliberately bland: an unresolved reference should contribute little, not hallucinate.
_GENERIC: dict[T, list[tuple[D, str, float, float, list[str], list[str]]]] = {
    T.OTHER: [
        (D.ATMOSPHERE, "the setting is legible at a glance and rewards a second look", 0.85, 0.6,
         ["emotional_register"], ["emotional_register:contemplative"]),
        (D.SPATIAL_LANGUAGE, "one organising move governs the whole composition", 0.88, 0.6,
         ["geometry_system"], ["geometry_system:orthogonal_grid"]),
        (D.LIGHTING_PHILOSOPHY, "light has a single identifiable origin", 0.85, 0.55,
         ["lighting_philosophy"], ["lighting_philosophy:grazing_wash"]),
        (D.MATERIAL_BEHAVIOUR, "the surface tells you how the thing was made", 0.86, 0.55,
         ["tectonic_logic"], ["tectonic_logic:assembled_modular"]),
        (D.RHYTHM_PACING, "a repeating element sets the tempo of the space", 0.85, 0.5,
         ["geometry_system"], ["geometry_system:modular_bay"]),
        (D.NARRATIVE_STRUCTURE, "arrival is separated from the destination by a prepared interval",
         0.88, 0.5, ["spatial_narrative"], ["spatial_narrative:arrival"]),
    ],
}


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


class CuratedReferenceAnalyzer:
    name = "curated"

    def __init__(self, ont: Ontology) -> None:
        self._ont = ont
        self._fixtures = all_fixtures(ont)
        self._alias_index: dict[str, str] = {}
        for rid, dna in self._fixtures.items():
            self._alias_index[_normalise(dna.identity.display_name)] = rid
            for a in dna.identity.aliases:
                self._alias_index[_normalise(a)] = rid

    def is_configured(self) -> bool:
        return True

    def known_ids(self) -> list[str]:
        return sorted(self._fixtures)

    # ---------- REF-00 support ----------
    def search(self, query: str, kind: T | None = None) -> list[ReferenceIdentity]:
        n = _normalise(query)
        if not n:
            return []
        scored: list[tuple[float, ReferenceDNA]] = []
        for rid, dna in self._fixtures.items():
            if kind and dna.identity.kind != kind:
                continue
            best = 0.0
            for cand in [dna.identity.display_name, *dna.identity.aliases]:
                best = max(best, difflib.SequenceMatcher(None, n, _normalise(cand)).ratio())
                if _normalise(cand).startswith(n) or n in _normalise(cand):
                    best = max(best, 0.9)
            if best > 0.35:
                scored.append((best, dna))
        scored.sort(key=lambda t: (-t[0], t[1].identity.reference_id))
        return [
            d.identity.model_copy(update={"query": query, "confidence": round(min(1.0, s), 3)})
            for s, d in scored[:6]
        ]

    # ---------- REF-01 ----------
    def analyse(self, *, query: str, kind: T | None = None, seed: int = 0) -> ReferenceDNA:
        rid = self._alias_index.get(_normalise(query))
        if rid is None:
            hits = self.search(query, kind)
            if hits and hits[0].confidence >= MATCH_THRESHOLD:
                rid = hits[0].reference_id
        if rid is not None:
            dna = self._fixtures[rid]
            return dna.model_copy(update={
                "identity": dna.identity.model_copy(update={"query": query})
            })
        return self._fallback(query, kind or T.OTHER, seed)

    def _fallback(self, query: str, kind: T, seed: int) -> ReferenceDNA:
        """Deterministic, ontology-grounded, deliberately low-salience."""
        rng = SeededRandom(seed, "ref_fallback", query)
        prof = profile(kind)
        rows = list(_GENERIC[T.OTHER])
        # bias the generic set toward this type's load-bearing dimensions where possible
        rows.sort(key=lambda r: (r[0] not in prof.load_bearing, r[0].value))

        traits: list[ReferenceTrait] = []
        for i, (dim, stmt, abstraction, salience, maps, suggests) in enumerate(rows):
            suggests = [s for s in suggests if s in self._ont.nodes]   # R-REF-19
            traits.append(ReferenceTrait(
                trait_id=f"t_gen_{i}", dimension=dim, statement=stmt,
                abstraction=abstraction,
                salience=round(min(salience, prof.cap_for(dim)), 3),
                maps_to=list(maps) if dim.value not in ("ERA", "CULTURAL_CONTEXT",
                                                        "TECHNOLOGICAL_CHARACTER") else [],
                suggests=suggests,
                evidence="generic profile: the query did not resolve to a curated reference",
            ))

        # the display name is the raw query; strip any proper noun from it for safety
        display = query.strip()[:80] or "unresolved reference"
        tokens = [
            SurfaceToken(token=w, category="PROPER_NOUN",
                         justification="unresolved query term, blocked by default")
            for w in detect_proper_nouns(display) + [display]
        ]
        legal_geom = "geometry_system:orthogonal_grid"
        legal_mat = "material:lime_plaster"
        literal = LiteralReading(
            label=f"a literal rendering of {display.lower()}",
            facet_values=[v for v in (legal_geom, legal_mat) if v in self._ont.nodes],
            surface_tokens=[display.lower()],
            prevalence=0.6,
            naive_rendering=f"A direct visual recreation of {display}, reproduced as set "
                            f"dressing rather than interpreted as a spatial idea.",
        )
        prof_dims = {t.dimension for t in traits}
        return ReferenceDNA(
            dna_id=deterministic_id("rdna", "fallback", display, self._ont.version),
            identity=ReferenceIdentity(
                reference_id=deterministic_id("ref", display), kind=kind,
                display_name=display, query=query, resolved_by="ANALYSER",
                confidence=0.35,
                blurb="Not a curated reference — a generic profile was used.",
            ),
            traits=traits, literal_reading=literal,
            surface_lexicon=SurfaceLexicon(tokens=tokens),
            coverage=[
                DimensionCoverage(dimension=d, trait_count=1,
                                  max_salience=max(t.salience for t in traits if t.dimension == d),
                                  load_bearing=d in prof.load_bearing)
                for d in sorted(prof_dims, key=lambda x: x.value)
            ],
            analysis_notes="fallback profile", analyser="curated:fallback",
        )
