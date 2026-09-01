"""Constraint checking over a candidate genotype assignment.

`excludes` edges reject outright. `requires` edges are closed (selecting a value
pulls its requirements in). `tensions_with` is *allowed* and priced into an
incoherence prior — never rejected, because tension is where the interesting
concepts come from.
"""
from __future__ import annotations

from app.domain.space import CreativeSearchSpace
from app.ontology.graph import Ontology

Assignment = dict[str, object]   # facet -> ref | list[ref]


def refs_of(assignment: Assignment) -> list[str]:
    out: list[str] = []
    for v in assignment.values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return out


def violated_exclusions(ont: Ontology, assignment: Assignment) -> list[tuple[str, str]]:
    refs = refs_of(assignment)
    bad: list[tuple[str, str]] = []
    for i, a in enumerate(refs):
        ex = ont.excludes(a)
        for b in refs[i + 1:]:
            if b in ex:
                bad.append((a, b))
    return bad


def is_feasible(ont: Ontology, assignment: Assignment, space: CreativeSearchSpace) -> bool:
    if violated_exclusions(ont, assignment):
        return False
    for facet, value in assignment.items():
        if facet == "material_primary":
            if not space.is_legal("material_palette", str(value)):
                return False
            continue
        if facet not in [d.facet_id for d in space.domains]:
            continue
        vals = [value] if isinstance(value, str) else list(value)  # type: ignore[arg-type]
        for v in vals:
            if not space.is_legal(facet, str(v)):
                return False
    return True


def requires_closure(ont: Ontology, refs: list[str]) -> list[str]:
    """Technology values pulled in by the genotype's own choices."""
    out: list[str] = []
    for r in refs:
        for t in ont.requires(r):
            if t not in out:
                out.append(t)
    return sorted(out)


def incoherence_prior(ont: Ontology, assignment: Assignment) -> float:
    """Sum of |weight| over tensions_with pairs present. Penalises doomed
    combinations at allocation time, before a model call is spent on them."""
    refs = set(refs_of(assignment))
    total = 0.0
    for r in refs:
        for other, w in ont.tensions(r):
            if other in refs:
                total += abs(w)
    return total / 2.0


def active_tensions(ont: Ontology, refs: list[str]) -> list[tuple[str, str, float]]:
    present = set(refs)
    seen: set[frozenset[str]] = set()
    out: list[tuple[str, str, float]] = []
    for r in present:
        for other, w in ont.tensions(r):
            if other in present:
                key = frozenset({r, other})
                if key not in seen:
                    seen.add(key)
                    out.append((r, other, w))
    return sorted(out)
