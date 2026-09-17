"""Deterministic conceptual-mutation provider.

Not a stub returning filler: it performs each operation's actual move against the
concept's real genotype and the programme's real assumptions, so the operators,
the constraint check, anti-repetition, provenance and the genotype dispatch are all
exercised with no model and no network. The prose is mechanical; the STRUCTURE and
the choices are real, which is the same bargain the phenotype mock already makes.

Seeded, so the same brief and seed produce the same transformations.
"""
from __future__ import annotations

from app.core.seeded import SeededRandom
from app.domain.cognition import (
    CognitiveOperation as Op, CreativeTransformation, FeasibilityRisk,
)

# Re-readings that change what an element DOES, not what it is called. Each pairs a
# conventional reading with an organisational consequence.
_REINTERPRETATIONS = (
    ("seating as furniture", "seating as a social landscape that shapes who meets whom",
     "occupation becomes topography rather than rows"),
    ("the entrance as a door", "the entrance as a compression released into the room",
     "arrival is a sequence with a held low point before the volume opens"),
    ("circulation as a corridor", "circulation as the primary social space",
     "movement and gathering share one volume instead of being separated"),
    ("the ceremonial focus as an object", "the focus as a condition of light and clearance",
     "the centre is defined by what surrounds it rather than by what stands there"),
    ("the boundary as a wall", "the boundary as a gradient of privacy",
     "enclosure is graded in depth rather than drawn as a line"),
)

_DISTORTIONS = (
    ("threshold count", "one threshold becomes a sequence of nine",
     "the approach dominates the plan and the room is reached only after a rhythm"),
    ("compression", "the low point is pushed to the limit of comfort",
     "the release into the main volume becomes the entire architectural event"),
    ("repetition", "a single bay is repeated far past structural necessity",
     "the field of supports becomes the space rather than defining it"),
    ("density of occupation", "the gathering is packed into a third of the area",
     "the remaining space reads as deliberate void and carries the ceremony"),
)

_SCALES = (
    ("a room", "a landscape", "the enclosure stops being a container and becomes terrain"),
    ("an object at the centre", "a field across the whole site",
     "there is no single focal object; the focus is distributed and read as a whole"),
    ("a detail", "the structural system itself",
     "what was an ornament at hand scale becomes what holds the roof up"),
)

_REMOVALS = (
    ("the central focal object", "the clearance and the light that fell on it now define the centre",
     "the ceremony is held by absence, and the surrounding geometry does the work"),
    ("the fixed seating hierarchy", "level changes replace assigned rank",
     "standing position is negotiated by the ground rather than allocated"),
    ("the visible structure", "the structure is buried in the ground plane and the perimeter",
     "the roof appears unsupported and the span becomes the subject"),
)

_SEQUENCES = (
    ("arrival is followed by reveal", "the reveal is placed before the arrival",
     "guests see the whole before they can reach it, and the walk becomes anticipation"),
    ("the journey ends at the focus", "the journey passes the focus and returns to it",
     "the space is read twice, once in approach and once in circumambulation"),
)

_ASSOCIATIONS = (
    ("thermal mass regulating temperature without machinery",
     "depth and enclosure are used to make comfort rather than equipment",
     "the section does the environmental work and the plan is freed"),
    ("a canopy that filters rather than blocks",
     "shelter is provided as a gradient of shade instead of a solid roof",
     "the boundary between inside and outside is never crossed at one line"),
)


def _pick(rng, table):
    return table[rng.randint(0, len(table) - 1)]


class MockCognitionProvider:
    name = "mock_cognition"
    model = "deterministic"

    def is_configured(self) -> bool:
        return True

    def propose_transformations(self, *, operation: str, context, n: int = 1,
                                seed: int = 0):
        op = Op(operation)
        rng = SeededRandom(seed, "mock_cognition", operation,
                           context.concept.concept_id)
        out = []
        for _ in range(max(1, n)):
            t = self._one(op, context, rng)
            if t is not None:
                out.append(t)
        return out

    def _one(self, op: Op, ctx, rng) -> CreativeTransformation | None:
        g = ctx.concept.genotype
        conf = round(0.5 + rng.random() * 0.4, 3)

        if op is Op.INVERT:
            assumptions = ctx.assumptions()          # already excludes blocked_by
            if not assumptions:
                return None
            a = assumptions[rng.randint(0, len(assumptions) - 1)]
            was, becomes, consequence = (
                a, f"the opposite of: {a.rstrip('.').lower()}",
                "the plan reorganises around the reversed condition")
        elif op is Op.REINTERPRET:
            was, becomes, consequence = _pick(rng, _REINTERPRETATIONS)
        elif op is Op.DISTORT:
            param, becomes, consequence = _pick(rng, _DISTORTIONS)
            was = f"{param} held at a conventional value"
        elif op is Op.REMOVE:
            was, becomes, consequence = _pick(rng, _REMOVALS)
            was = f"{was} is treated as essential"
        elif op is Op.SCALE:
            frm, to, consequence = _pick(rng, _SCALES)
            was, becomes = f"the design is read as {frm}", f"it is read as {to}"
        elif op is Op.SEQUENCE:
            was, becomes, consequence = _pick(rng, _SEQUENCES)
            was = f"the journey assumes {was}"
        elif op is Op.ASSOCIATE:
            src = ctx.principle_statements[0] if ctx.principle_statements else _pick(rng, _ASSOCIATIONS)[0]
            _, becomes, consequence = _pick(rng, _ASSOCIATIONS)
            was = f"transferable relationship: {src}"
        elif op is Op.HYBRIDISE:
            if ctx.partner is None:
                return None
            pg = ctx.partner.genotype
            was = (f"{g.occupation_staging.value.split(':')[-1]} organisation and "
                   f"{pg.occupation_staging.value.split(':')[-1]} organisation are treated as alternatives")
            becomes = "they are held together by one shared ordering behaviour"
            consequence = ("the plan carries one concept's form with the other's "
                           "occupation, which neither could support alone")
        elif op is Op.EVOLVE:
            finding = ctx.critic_findings[0] if ctx.critic_findings else "an unresolved weakness"
            was = f"the concept currently fails: {finding}"
            becomes = "one conceptual variable is moved while the identity is held"
            consequence = ("the same architectural language resolves the weakness "
                           "through a different organisation")
        else:
            return None

        return CreativeTransformation(
            transformation_id="pending",          # the engine assigns the stable id
            operation=op,
            source_concept_id=ctx.concept.concept_id,
            assumption_or_principle=was,
            transformation=becomes,
            new_principle=f"{becomes}; {consequence}",
            spatial_or_design_consequence=consequence,
            novelty_rationale="departs from the conventional reading of this element",
            confidence=conf,
            feasibility_risk=(FeasibilityRisk.RISKY if op in (Op.DISTORT, Op.REMOVE)
                              else FeasibilityRisk.VALID),
        )
