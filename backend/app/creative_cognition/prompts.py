"""Operation-specific instructions.

There is deliberately no general "be creative" prompt. Each operation states one
cognitive move, names the facts that may not be altered, and demands a structured
answer. A model asked to be creative reaches for adjectives; a model asked to
invert a stated assumption has to produce a different organisation.

The provider is told what is FACT (checked deterministically downstream and not
its business) and what is ASSUMPTION (its business entirely). That distinction is
the whole reason these prompts are separate from synthesis prompts.
"""
from __future__ import annotations

from app.domain.cognition import CognitiveOperation as Op

SYSTEM = (
    "You perform ONE named conceptual operation on an architectural concept and "
    "return structured data. You do not write descriptions, you do not choose "
    "materials for their looks, and you never restate the input. "
    "Constraints given as FACTS are verified by other systems: never alter them, "
    "never restate them as your idea, and never claim to satisfy one. "
    "Assumptions are conventions, not requirements — those are what you may move. "
    "Answer only with the requested fields, each a single plain sentence."
)

# What each operation is actually asking for. Written as a task, not a persona.
_OPERATION_TASK: dict[Op, str] = {
    Op.REINTERPRET: (
        "Find a different legitimate reading of what this brief asks for, without "
        "changing a single stated fact. Re-read one element as the thing it DOES "
        "rather than the thing it IS — seating as a social landscape, an entrance as "
        "compression and release, a corridor as a transition device. "
        "A reinterpretation that does not change how the space is organised is a "
        "synonym, and a synonym is a failed answer."
    ),
    Op.INVERT: (
        "One listed assumption is a convention rather than a requirement. Reverse it "
        "and follow the consequence. Centre becomes displaced, symmetry becomes "
        "asymmetry, visible becomes concealed, static becomes sequential. "
        "Only assumptions in the ASSUMPTIONS list may be inverted; anything under "
        "FACTS is fixed. State what the reversal forces the plan to do differently."
    ),
    Op.DISTORT: (
        "Take ONE meaningful parameter — density, compression, repetition, height, "
        "privacy, threshold count, span — and push it far past its conventional "
        "range until a different spatial strategy becomes necessary. "
        "The test is that the exaggeration FORCES a new organisation, not that it "
        "sounds dramatic. Random extremity is a failed answer."
    ),
    Op.REMOVE: (
        "Identify an element the concept currently treats as essential, remove it, "
        "and state what must now carry its job. "
        "This is not deletion: name the dependency that breaks, then name the "
        "compensating spatial mechanism that replaces it. A thinner version of the "
        "same design is a failed answer."
    ),
    Op.SCALE: (
        "Change the scale relationship, not only the dimensions. An object becomes a "
        "field, a room becomes a landscape, a single threshold becomes a repeated "
        "series, a detail becomes the structural system. "
        "State what the change of scale does to how a person reads the space."
    ),
    Op.HYBRIDISE: (
        "Two concepts are supplied. Find the conceptual relationship that could hold "
        "them together — a shared underlying behaviour, not a visual blend. "
        "State what the combination makes possible that neither parent could do "
        "alone. Mixing their appearances is a failed answer."
    ),
    Op.ASSOCIATE: (
        "A principle from a distant domain is supplied, already abstracted into a "
        "relational statement. Map that RELATIONSHIP into this design problem. "
        "Never reproduce the source's appearance, vocabulary, or named objects — "
        "transfer only how it behaves."
    ),
    Op.SEQUENCE: (
        "Treat the design as an experience over time rather than an object. "
        "Reorder or rethink the sequence of moments — arrival, compression, "
        "transition, reveal, gathering, pause, release — so the journey itself "
        "changes. State the spatial consequence of the new order, not the order alone."
    ),
    Op.EVOLVE: (
        "A critic has found a specific weakness, supplied below. Keep what makes this "
        "concept itself — its locked identity is listed and may not change — and "
        "alter ONE other conceptual variable so the weakness stops applying. "
        "You may change direction; you may not change identity. Fixing everything is "
        "a failed answer."
    ),
}

FIELDS = (
    "assumption_or_principle : the specific thing you are acting on\n"
    "transformation          : the move you are making, in one sentence\n"
    "new_principle           : the design principle that results\n"
    "spatial_or_design_consequence : what is physically different about the space\n"
    "novelty_rationale       : why this is not the obvious answer\n"
    "confidence              : 0.0 to 1.0"
)


def build(operation: Op, context: str) -> tuple[str, str]:
    """-> (system, user). Context is assembled by the caller from structured data."""
    task = _OPERATION_TASK[operation]
    user = (
        f"OPERATION = {operation.value}\n\n"
        f"{task}\n\n"
        f"{context}\n\n"
        f"Return exactly these fields:\n{FIELDS}"
    )
    return SYSTEM, user
