"""The nine conceptual operations.

Each one builds the CONTEXT for its operation, asks the provider for a structured
transformation, and names which existing genotype operator should execute it.
None of them mutates a genotype: that stays the deterministic layer's job, which
is what keeps a speculative idea from becoming an invalid concept.

Dispatch table — conceptual operation to the primitive that carries it out:

    REINTERPRET -> reinterpret     (resample non-identity facets)
    INVERT      -> invert          (ontology inverse_of edges)
    DISTORT     -> attenuate       (driven hard, magnitude >= 0.75)
    REMOVE      -> remove          (drop a narrative beat, compensate)
    SCALE       -> scale_up        (ordered rank move)
    HYBRIDISE   -> hybridise       (two parents, handled by the engine)
    ASSOCIATE   -> reinterpret     (the transferred relation reorganises the plan)
    SEQUENCE    -> resequence      (reorder the journey)
    EVOLVE      -> from REPAIR_ROUTE, chosen by the critic finding
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.ids import deterministic_id
from app.domain.antibrief import AntiBrief
from app.domain.cognition import (
    CognitiveOperation as Op, CreativeTransformation, FeasibilityRisk,
)
from app.domain.brief import DesignProgram
from app.domain.concept import ConceptDNA
from app.repair.engine import REPAIR_ROUTE

GENOTYPE_OP: dict[Op, str] = {
    Op.REINTERPRET: "reinterpret",
    Op.INVERT: "invert",
    Op.DISTORT: "attenuate",
    Op.REMOVE: "remove",
    Op.SCALE: "scale_up",
    Op.HYBRIDISE: "hybridise",
    # `abstract` only raises cultural-lineage abstraction — that makes a
    # reference less literal, which the injection already does. Transferring a
    # distant relationship has to change how the space is ORGANISED.
    Op.ASSOCIATE: "reinterpret",
    Op.SEQUENCE: "resequence",
    Op.EVOLVE: "reinterpret",      # overridden per finding via REPAIR_ROUTE
}

# DISTORT is only distortion if it is pushed. Below this the operator behaves like
# ordinary attenuation and the result is a variant, not a new direction.
DISTORT_MAGNITUDE = 0.85


@dataclass(frozen=True)
class CognitionContext:
    """Everything an operation may see. Assembled from structured data only —
    no prose is passed through from anywhere the engine does not control."""
    concept: ConceptDNA
    program: DesignProgram
    antibrief: AntiBrief | None = None
    principle_statements: tuple[str, ...] = ()
    partner: ConceptDNA | None = None            # HYBRIDISE
    critic_findings: tuple[str, ...] = ()        # EVOLVE
    explored_principles: tuple[str, ...] = ()    # anti-repetition

    # ---- context rendering -------------------------------------------------
    def facts(self) -> list[str]:
        """Hard invariants. Stated so the provider knows what it may not touch —
        never so it can claim to have satisfied them."""
        p = self.program
        sem = p.semantic
        out = ([f"event: {sem.profile.identity.event_type_label} "
                f"({sem.profile.identity.event_family or 'no family'})",
                f"primary focus: {sem.intent.primary_focus}",
                f"audience relationship: {sem.profile.audience_relationship}"]
               if sem else [f"typology: {p.typology.value}"])
        out += [f"capacity: {p.capacity.guests} guests",
                f"site: {p.site.width_m:.0f} x {p.site.depth_m:.0f} m, {p.site.kind.lower()}",
                f"climate: {p.site.climate.label.replace('_', ' ')}"]
        out += [f"invariant: {c.statement}" for c in p.invariants if c.kind == "HARD"][:6]
        return out

    def primitives(self) -> list[tuple[str, str]]:
        """The conceptual pairs this event is organised by: performer/audience for a
        concert, kitchen/dining for a restaurant, object/circulation for an exhibition.
        These are what an operation transforms, so INVERT on a concert inverts the
        stage/audience hierarchy rather than a ceremony it never had."""
        sem = self.program.semantic
        if sem is None:
            return []
        out = []
        for pair in sem.profile.relationships:
            a, _, b = pair.partition("|")
            if a and b:
                out.append((a.replace("_", " "), b.replace("_", " ")))
        return out

    def focus_label(self) -> str:
        sem = self.program.semantic
        return (sem.intent.primary_focus.lower() if sem and sem.intent.primary_focus
                else "focal space")

    def event_label(self) -> str:
        sem = self.program.semantic
        return sem.profile.identity.event_type_label.lower() if sem else "event"

    def assumptions(self) -> list[str]:
        """Only assumptions that are NOT blocked by a sacred constraint.

        `blocked_by` is set by the anti-brief when an assumption restates a hard
        invariant. Those are facts wearing an assumption's clothing, and offering
        one for inversion would invite the provider to break a constraint.
        """
        if not self.antibrief:
            return []
        return [a.statement for a in self.antibrief.questioned_assumptions
                if a.blocked_by is None]

    def render(self, operation: Op) -> str:
        g = self.concept.genotype
        blocks = [
            "FACTS (fixed, verified elsewhere — do not alter or restate):",
            *(f"  - {f}" for f in self.facts()),
            "",
            "CURRENT CONCEPT:",
            f"  thesis: {self.concept.phenotype.design_thesis[:240]}",
            f"  language: {g.architectural_language.value.split(':')[-1]}",
            f"  geometry: {g.geometry.system.split(':')[-1]}",
            f"  structure: {g.structural_logic.value.split(':')[-1]}",
            f"  staging: {g.occupation_staging.value.split(':')[-1]}",
            f"  sequence: {' -> '.join(s.split(':')[-1] for s in g.spatial_narrative)}",
        ]
        prims = self.primitives()
        if prims:
            blocks += ["", "DESIGN PRIMITIVES (the relationships this event is organised by):",
                       *(f"  - {a} / {b}" for a, b in prims)]
        if operation is Op.INVERT:
            a = self.assumptions()
            blocks += ["", "ASSUMPTIONS (conventions you MAY reverse):",
                       *(f"  - {s}" for s in a)] if a else \
                      ["", "ASSUMPTIONS: none available — do not invent one."]
        if operation is Op.HYBRIDISE and self.partner is not None:
            pg = self.partner.genotype
            blocks += ["", "SECOND CONCEPT:",
                       f"  thesis: {self.partner.phenotype.design_thesis[:240]}",
                       f"  language: {pg.architectural_language.value.split(':')[-1]}",
                       f"  staging: {pg.occupation_staging.value.split(':')[-1]}"]
        if operation is Op.ASSOCIATE and self.principle_statements:
            blocks += ["", "TRANSFERABLE PRINCIPLE (already abstracted — map the "
                       "relationship, never the appearance):",
                       *(f"  - {s}" for s in self.principle_statements)]
        if operation is Op.EVOLVE:
            blocks += ["", "CRITIC FINDINGS (what is wrong):",
                       *(f"  - {s}" for s in self.critic_findings),
                       "", "LOCKED IDENTITY (may be enriched, never replaced):",
                       f"  - {g.architectural_language.value.split(':')[-1]}",
                       f"  - {g.structural_logic.value.split(':')[-1]}"]
        if self.explored_principles:
            blocks += ["", "ALREADY EXPLORED (do not propose these again):",
                       *(f"  - {s}" for s in self.explored_principles[:8])]
        return "\n".join(blocks)


def genotype_op_for(operation: Op, findings: tuple[str, ...] = ()) -> str:
    """EVOLVE routes through the existing REPAIR_ROUTE so a circulation complaint
    and a span complaint evolve differently. Everything else is a fixed dispatch."""
    if operation is not Op.EVOLVE:
        return GENOTYPE_OP[operation]
    for code in findings:
        route = REPAIR_ROUTE.get(code)
        if route:
            first = route[0]
            if not first.startswith("__"):     # __closure__ / __re_express__ are repair-only
                return first
    return GENOTYPE_OP[Op.EVOLVE]


def magnitude_for(operation: Op, base: float = 0.5) -> float:
    if operation is Op.DISTORT:
        return DISTORT_MAGNITUDE
    if operation in (Op.REINTERPRET, Op.INVERT):
        return max(base, 0.6)
    return base


def check_constraints(t: CreativeTransformation, program: DesignProgram) -> CreativeTransformation:
    """Deterministic verification of a proposed transformation.

    The provider is never trusted on feasibility. A transformation that names a
    sacred constraint as the thing it intends to move is REJECTED here, before any
    genotype is touched — which is how an idea can be speculative without ever
    being silently invalid.
    """
    text = f"{t.assumption_or_principle} {t.transformation} {t.new_principle}".lower()
    violated = [c.constraint_id for c in program.invariants
                if c.sacred and _mentions(text, c.statement)]
    if violated:
        return t.model_copy(update={
            "constraint_violations": violated,
            "feasibility_risk": FeasibilityRisk.REJECTED,
        })
    return t


def _mentions(text: str, statement: str) -> bool:
    """A transformation "mentions" a constraint when it names the constraint's own
    distinctive words. Deliberately conservative: a false positive costs one
    discarded idea, a false negative costs a violated invariant."""
    words = [w for w in statement.lower().split() if len(w) > 5][:6]
    hits = sum(1 for w in words if w.strip(".,") in text)
    return hits >= 2


def new_transformation_id(exploration_id: str, concept_id: str, operation: Op, n: int) -> str:
    return deterministic_id("ct", exploration_id, concept_id, operation.value, str(n))
