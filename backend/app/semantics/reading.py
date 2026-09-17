"""The reasoning model's contract for understanding a brief.

Deliberately flat and string-typed: a small local model must be able to satisfy it
under a grammar constraint. Everything here is a PROPOSAL. The merge in
`intelligence.py` decides what survives, against the knowledge base, the scope rules
and the user's own words — prose from this schema never becomes system truth
without passing that gate.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Loose(BaseModel):
    # extra keys from a chatty model are ignored rather than failing the whole reading
    model_config = ConfigDict(extra="ignore")


class ZoneProposal(_Loose):
    key: str = Field(description="lower_snake identifier, e.g. dance_floor")
    label: str
    role: str = Field(description="one of: arrival, focal, performance, audience, "
                                  "participation, social, hospitality, dining, display, "
                                  "ceremony, circulation, service, technical, backstage, "
                                  "media, support, outdoor, retail, work")
    priority: str = Field(default="recommended", description="required | recommended | optional")
    rationale: str = ""


class SemanticReading(_Loose):
    event_type_label: str = Field(description="what this event or space is, in a few words")
    event_family: str = Field(default="", description="the broader family, lower_snake")
    domain: str = Field(default="event", description="event | interior | architecture | "
                                                     "installation | landscape")
    subtype: str = ""
    primary_activities: list[str] = Field(default_factory=list,
                                          description="lower_snake activity keys")
    secondary_activities: list[str] = Field(default_factory=list)
    audience_relationship: str = Field(default="none", description="frontal | surround | "
                                       "immersive | distributed | participatory | "
                                       "processional | convivial | none")
    focal_relationship: str = ""
    participants: list[str] = Field(default_factory=list)
    atmosphere: list[str] = Field(default_factory=list)
    cultural_context: list[str] = Field(default_factory=list)
    zones: list[ZoneProposal] = Field(default_factory=list)
    required_elements: list[str] = Field(default_factory=list)
    recommended_elements: list[str] = Field(default_factory=list)
    optional_elements: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)
    visual_priorities: list[str] = Field(default_factory=list)
    must_communicate: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    operational_needs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


SYSTEM = """You are the design-intelligence stage of a spatial design engine. You read a \
brief and state, in structure, what the client is actually asking to be created. You do \
not design anything. Another system will explore design options from your reading.

Reason about:
- what this event or space IS, and what it is NOT. Families are context, not identity: a \
Sangeet and a Haldi are both wedding celebrations and share almost no programme.
- what people do there, who they are, and where their attention goes.
- which zones those activities need, and which are optional.
- what would make an image recognisably THIS event rather than a generic one.
- what must NOT appear: elements that belong to a different event, rite or tradition. \
Never assume a religious or ritual element the brief does not ask for.
- what you are unsure of.

Prefer the given activity keys when one fits; invent a new lower_snake key only when none \
does. Every list item is a short phrase, not a paragraph. Return only the JSON object."""


def build_user_prompt(*, brief_text: str, selections: dict[str, str], grounding: dict,
                      activity_keys: list[str], family_keys: list[str]) -> str:
    lines = ["## BRIEF", brief_text.strip(), ""]
    chosen = {k: v for k, v in selections.items() if v}
    if chosen:
        lines.append("## SELECTED IN THE FORM")
        lines += [f"- {k}: {v}" for k, v in chosen.items()]
        lines.append("")
    lines.append("## ALREADY ESTABLISHED (deterministic, treat as fact)")
    lines += [f"- {k}: {v}" for k, v in grounding.items() if v]
    lines += ["", "## KNOWN ACTIVITY KEYS", ", ".join(activity_keys), "",
              "## KNOWN FAMILY KEYS", ", ".join(family_keys), "",
              "## TASK", "Return the semantic reading as JSON."]
    return "\n".join(lines)
