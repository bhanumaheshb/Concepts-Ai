"""Principle resolution.

Runtime principles (reference-derived) are NOT in the ontology's frozen dict. Every
lookup must therefore go through an index rather than `ont.principles[...]`, or a
runtime principle's forbidden_surface_tokens are silently dropped from the negative
prompt — a failure that passes every existing test.

Lives in `ontology/` rather than `references/` so the prompt compiler can resolve a
principle without depending on the reference module (layering: prompt → ontology).
"""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from app.domain.common import NicheRole
from app.ontology.graph import Ontology, Principle

RUNTIME_PREFIX = "refprin_"


@runtime_checkable
class PrincipleIndex(Protocol):
    def get(self, principle_id: str) -> Principle | None: ...
    def all_for(self, role: NicheRole) -> list[Principle]: ...
    def runtime_ids(self) -> list[str]: ...


class OntologyPrincipleIndex:
    """The default: exactly the ontology's own principles, current behaviour."""

    def __init__(self, ont: Ontology) -> None:
        self._ont = ont

    def get(self, principle_id: str) -> Principle | None:
        return self._ont.principles.get(principle_id)

    def all_for(self, role: NicheRole) -> list[Principle]:
        return [p for p in self._ont.principles.values() if _role_ok(p, role)]

    def runtime_ids(self) -> list[str]:
        return []


class MergedPrincipleIndex:
    """Ontology principles + this exploration's runtime principles.

    The ontology is never mutated. Runtime ids carry the `refprin_` prefix so they can
    never collide with a YAML-authored id.
    """

    def __init__(self, ont: Ontology, runtime: Iterable[Principle] = ()) -> None:
        self._ont = ont
        self._runtime: dict[str, Principle] = {}
        for p in runtime:
            if not p.id.startswith(RUNTIME_PREFIX):
                raise ValueError(f"runtime principle id must start with {RUNTIME_PREFIX!r}: {p.id}")
            if p.id in ont.principles:
                raise ValueError(f"runtime principle id collides with an ontology id: {p.id}")
            self._runtime[p.id] = p

    def get(self, principle_id: str) -> Principle | None:
        return self._runtime.get(principle_id) or self._ont.principles.get(principle_id)

    def all_for(self, role: NicheRole) -> list[Principle]:
        out = [p for p in self._ont.principles.values() if _role_ok(p, role)]
        out += [p for p in self._runtime.values() if _role_ok(p, role)]
        return out

    def runtime_ids(self) -> list[str]:
        return sorted(self._runtime)

    @property
    def runtime(self) -> list[Principle]:
        return [self._runtime[k] for k in sorted(self._runtime)]


def _role_ok(p: Principle, role: NicheRole) -> bool:
    """`role_eligibility=None` preserves the pre-existing behaviour, where eligibility
    was decided solely by the caller's ELIGIBLE_ROLES set."""
    return p.role_eligibility is None or role in p.role_eligibility


def index_for(ont: Ontology, runtime: Iterable[Principle] = ()) -> PrincipleIndex:
    runtime = list(runtime)
    return MergedPrincipleIndex(ont, runtime) if runtime else OntologyPrincipleIndex(ont)
