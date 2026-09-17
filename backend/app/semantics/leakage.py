"""Leakage detection: did something from another event get into this one?

Deterministic and shared. The same function checks a brief's programme, a genotype,
a scene graph, a model's prose, a visual intent and a final image prompt, so there
is exactly one definition of "leak" in the system.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.semantics import EventProfile
from app.semantics.knowledge import Knowledge


@dataclass(frozen=True)
class Leak:
    element: str
    label: str
    phrase: str
    where: str
    rule: str

    def describe(self) -> str:
        return f"'{self.phrase}' ({self.label}) in {self.where} — {self.rule}"


def find_leaks(knowledge: Knowledge, profile: EventProfile, text: str,
               where: str = "text") -> list[Leak]:
    """Forbidden elements mentioned positively in `text`.

    A negated mention ("no mandap", "without a ritual fire") is not a leak: that is
    the concept or the prompt correctly stating what it is not.
    """
    if not text:
        return []
    forbidden = {e.key: e for e in profile.elements if e.status.value == "FORBIDDEN"}
    if not forbidden:
        return []
    out: list[Leak] = []
    seen: set[str] = set()
    for m in knowledge.element_index.find(text):
        if m.negated or m.key not in forbidden or m.key in seen:
            continue
        seen.add(m.key)
        el = forbidden[m.key]
        out.append(Leak(element=m.key, label=el.label, phrase=m.phrase, where=where,
                        rule=el.rule or el.rationale))
    return out


def find_leaks_in(knowledge: Knowledge, profile: EventProfile,
                  fields: dict[str, str]) -> list[Leak]:
    out: list[Leak] = []
    for where, text in fields.items():
        out.extend(find_leaks(knowledge, profile, text, where))
    return out
