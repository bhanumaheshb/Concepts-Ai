"""Curated reference fixtures: YAML → validated ReferenceDNA.

Same three-representation pattern as the ontology — YAML in git is the source of truth,
a frozen dict is the runtime, and the checksum is the version.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.ids import deterministic_id
from app.domain.reference import (
    DimensionCoverage, LiteralReading, ReferenceDimension, ReferenceDNA,
    ReferenceIdentity, ReferenceTrait, ReferenceType, SurfaceLexicon, SurfaceToken,
)
from app.ontology.graph import Ontology
from app.references.types import LOAD_BEARING_SALIENCE, cap_salience, coverage_ok, profile

DATA_ROOT = Path(__file__).parent / "data"


class FixtureError(RuntimeError):
    pass


def _build_dna(raw: dict, ont: Ontology, path: Path) -> ReferenceDNA:
    ident = raw["identity"]
    kind = ReferenceType(ident["kind"])
    identity = ReferenceIdentity(
        reference_id=ident["reference_id"], kind=kind,
        display_name=ident["display_name"], query=ident["display_name"],
        resolved_by="CURATED", confidence=1.0,
        blurb=ident.get("blurb", ""), aliases=list(ident.get("aliases", [])),
    )

    traits: list[ReferenceTrait] = []
    for t in raw["traits"]:
        dim = ReferenceDimension(t["dimension"])
        # rule 3: every `suggests` value must resolve; drop and report rather than invent
        unknown = [s for s in t.get("suggests", []) if s not in ont.nodes]
        if unknown:
            raise FixtureError(f"{path.name}:{t['id']} suggests unknown ontology refs {unknown}")
        traits.append(ReferenceTrait(
            trait_id=t["id"], dimension=dim, statement=t["statement"],
            abstraction=float(t["abstraction"]), salience=float(t["salience"]),
            surface_tokens=list(t.get("surface_tokens", [])),
            maps_to=list(t.get("maps_to", [])), suggests=list(t.get("suggests", [])),
            evidence=t.get("evidence", ""),
        ))
    traits = cap_salience(kind, traits)

    ok, detail = coverage_ok(kind, traits)
    if not ok:
        raise FixtureError(
            f"{path.name}: R-REF-05 — fewer than 3 load-bearing dimensions at salience "
            f">= {LOAD_BEARING_SALIENCE}; missing any of {detail}"
        )

    lr = raw["literal_reading"]
    bad = [v for v in lr["facet_values"] if v not in ont.nodes]
    if bad:
        raise FixtureError(f"{path.name}: literal_reading has unknown refs {bad}")
    if not lr.get("naive_rendering", "").strip():
        raise FixtureError(f"{path.name}: rule 5 — naive_rendering is required")
    literal = LiteralReading(
        label=lr["label"], facet_values=list(lr["facet_values"]),
        surface_tokens=list(lr.get("surface_tokens", [])),
        prevalence=float(lr.get("prevalence", 0.9)),
        naive_rendering=lr["naive_rendering"].strip(),
    )

    tokens: list[SurfaceToken] = []
    for entry in raw.get("surface_lexicon", []):
        if not entry.get("transformed_to") and not entry.get("justification"):
            raise FixtureError(
                f"{path.name}: rule 6 — token {entry['token']!r} needs transformed_to "
                f"or an explicit justification"
            )
        tokens.append(SurfaceToken(
            token=entry["token"], category=entry["category"],
            transformed_to=entry.get("transformed_to"),
            justification=entry.get("justification", ""),
        ))
    # the literal reading's own tokens are blocked too
    known = {t.token.lower() for t in tokens}
    for tok in literal.surface_tokens:
        if tok.lower() not in known:
            tokens.append(SurfaceToken(
                token=tok, category="SET_ELEMENT",
                justification="literal-reading vocabulary, blocked by construction",
            ))
    lexicon = SurfaceLexicon(tokens=tokens)

    prof = profile(kind)
    coverage = [
        DimensionCoverage(
            dimension=d, trait_count=len([t for t in traits if t.dimension == d]),
            max_salience=max((t.salience for t in traits if t.dimension == d), default=0.0),
            load_bearing=d in prof.load_bearing,
        )
        for d in sorted({t.dimension for t in traits}, key=lambda x: x.value)
    ]

    return ReferenceDNA(
        dna_id=deterministic_id("rdna", identity.reference_id, ont.version),
        identity=identity, traits=traits, literal_reading=literal,
        surface_lexicon=lexicon, coverage=coverage,
        analysis_notes=raw.get("notes", ""), analyser=None,
    )


@lru_cache(maxsize=4)
def load_fixtures(version: str, ontology_version: str) -> dict[str, ReferenceDNA]:
    """`ontology_version` is part of the cache key: fixtures are validated against the
    ontology, so a graph change must re-validate them."""
    from app.ontology.graph import load_ontology
    ont = load_ontology(version if version.startswith("v") else "v1")
    root = DATA_ROOT / version
    if not root.exists():
        raise FixtureError(f"reference fixture set {version} not found at {root}")
    out: dict[str, ReferenceDNA] = {}
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        dna = _build_dna(raw, ont, path)
        out[dna.identity.reference_id] = dna
    return out


def fixtures_checksum(version: str = "v1") -> str:
    h = hashlib.sha256()
    for p in sorted((DATA_ROOT / version).glob("*.yaml")):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def all_fixtures(ont: Ontology, version: str = "v1") -> dict[str, ReferenceDNA]:
    return load_fixtures(version, ont.version)
