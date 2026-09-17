"""Creative Cognition — the conceptual layer above the deterministic mutation system.

    conceptual operation  ->  structured transformation  ->  EXISTING genotype operator

The layer proposes moves. It never mutates a genotype, never decides feasibility,
and never touches diversity arithmetic — those stay where they already are, which
is what allows exploration to be speculative without becoming unsound.

Disabled by default. With `cognition=None` the pipeline is byte-for-byte the one
that existed before this module, which the baseline tests assert.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.ids import deterministic_id
from app.core.seeded import SeededRandom
from app.creative_cognition.memory import CreativeMemory
from app.creative_cognition.operators import (
    CognitionContext, check_constraints, genotype_op_for, magnitude_for,
    new_transformation_id,
)
from app.domain.cognition import (
    CognitionRecord, CognitiveOperation as Op, CreativeTransformation,
)
from app.domain.common import IDENTITY_FACETS
from app.domain.concept import ConceptDNA, Lineage
from app.diversity.metric import genotype_distance
from app.mutation.operators import apply_operator, op_hybridise
from app.ontology.graph import Ontology

# Which operations run, in order. EXPAND runs before phenotype synthesis; EVOLVE
# runs after critics, because it needs findings to respond to.
EXPAND_OPS: tuple[Op, ...] = (
    Op.REINTERPRET, Op.INVERT, Op.SEQUENCE, Op.DISTORT,
    Op.SCALE, Op.REMOVE, Op.ASSOCIATE, Op.HYBRIDISE,
)


@dataclass
class CognitionConfig:
    """Conservative by default: a small budget that cannot dominate the run."""
    budget: int = 8                      # total transformations per exploration
    max_per_candidate: int = 2
    max_generations: int = 1
    # NOTE: no sampling parameter. Breadth comes from the operations and the
    # budget, never from decoding noise — the AST test enforces this.
    novelty_threshold: float = 0.6       # memory Jaccard above this => already explored
    enabled_operations: tuple[Op, ...] = EXPAND_OPS


class CreativeCognition:
    def __init__(self, ont: Ontology, provider, config: CognitionConfig | None = None) -> None:
        self.ont = ont
        self.provider = provider          # ConceptualMutationProvider protocol only
        self.config = config or CognitionConfig()
        self.memory = CreativeMemory()

    # ------------------------------------------------------------------ expand
    def expand(
        self, *, concepts: list[ConceptDNA], program, antibrief, space,
        exploration_id: str, seed: int, principle_statements: tuple[str, ...] = (),
    ) -> list[ConceptDNA]:
        """Propose conceptual mutations of the solved candidates and return the ones
        the deterministic layer could actually build. Never returns fewer than it
        was given: cognition ADDS candidates, it does not filter them."""
        if not concepts or self.config.budget <= 0:
            return concepts

        rng = SeededRandom(seed, "cognition", exploration_id)
        produced: list[ConceptDNA] = []
        spent = 0

        for op in self.config.enabled_operations:
            if spent >= self.config.budget:
                break
            for i, parent in enumerate(concepts):
                if spent >= self.config.budget:
                    break
                if self.memory.count_for(op.value) >= self.config.max_per_candidate:
                    break
                partner = self._partner(concepts, i, op)
                ctx = CognitionContext(
                    concept=parent, program=program, antibrief=antibrief,
                    principle_statements=principle_statements, partner=partner,
                    explored_principles=self.memory.explored_principles(),
                )
                # INVERT with nothing invertible is a no-op, not an invitation to
                # invent an assumption.
                if op is Op.INVERT and not ctx.assumptions():
                    continue

                t = self._propose(op, ctx, exploration_id, parent, spent, seed)
                spent += 1
                if t is None:
                    continue
                child = self._execute(t, parent, partner, space, rng, program)
                if child is not None:
                    produced.append(child)
        return concepts + produced

    # ------------------------------------------------------------------ evolve
    def evolve(
        self, *, concepts: list[ConceptDNA], program, antibrief, space,
        exploration_id: str, seed: int,
    ) -> list[ConceptDNA]:
        """Respond to critic findings by changing DIRECTION, not by fixing defects.

        Repair already fixes defects and preserves identity exactly; evolve keeps the
        identity but is allowed to move a different conceptual variable, so a concept
        that fails can come back as a different answer rather than a patched one.
        """
        if self.config.max_generations <= 0:
            return concepts
        rng = SeededRandom(seed, "cognition_evolve", exploration_id)
        out: list[ConceptDNA] = []
        spent = 0
        for parent in concepts:
            ev = parent.evaluation
            if ev is None or ev.gate_passed or spent >= self.config.budget:
                continue
            findings = tuple(f.code for f in ev.blockers()[:3])
            ctx = CognitionContext(
                concept=parent, program=program, antibrief=antibrief,
                critic_findings=tuple(f.statement for f in ev.blockers()[:3]),
                explored_principles=self.memory.explored_principles(),
            )
            t = self._propose(Op.EVOLVE, ctx, exploration_id, parent, spent, seed,
                              findings=findings)
            spent += 1
            if t is None:
                continue
            child = self._execute(t, parent, None, space, rng, program)
            if child is not None:
                out.append(child)
        return concepts + out

    # ---------------------------------------------------------------- internals
    def _partner(self, concepts, i, op) -> ConceptDNA | None:
        """HYBRIDISE needs a DISTANT partner, not the neighbour — combining two
        adjacent concepts produces their average, which is the opposite of the point."""
        if op is not Op.HYBRIDISE or len(concepts) < 2:
            return None
        return concepts[(i + len(concepts) // 2) % len(concepts)]

    def _propose(self, op, ctx, exploration_id, parent, n, seed,
                 findings: tuple[str, ...] = ()) -> CreativeTransformation | None:
        if self.provider is None or not self.provider.is_configured():
            return None
        try:
            proposals = self.provider.propose_transformations(
                operation=op.value, context=ctx, n=1, seed=seed + n)
        except Exception as exc:                       # a failed idea is not a failed run
            self.memory.record(CognitionRecord(
                transformation_id=new_transformation_id(exploration_id, parent.concept_id, op, n),
                operation=op, parent_id=parent.concept_id,
                rejection_reason=f"PROVIDER_ERROR: {type(exc).__name__}"))
            return None
        if not proposals:
            return None

        t = proposals[0]
        t = t.model_copy(update={
            "transformation_id": new_transformation_id(exploration_id, parent.concept_id, op, n),
            "operation": op,
            "source_concept_id": parent.concept_id,
            "parent_id": parent.concept_id,
            "second_parent_id": ctx.partner.concept_id if ctx.partner else None,
            "genotype_operation": genotype_op_for(op, findings),
            "magnitude": magnitude_for(op),
        })
        # Deterministic verification. The provider is never trusted here.
        t = check_constraints(t, ctx.program)
        if not t.executable:
            self.memory.record(CognitionRecord(
                transformation_id=t.transformation_id, operation=op,
                parent_id=parent.concept_id, feasibility_risk=t.feasibility_risk,
                rejection_reason="CONSTRAINT_VIOLATION:" + ",".join(t.constraint_violations)))
            return None
        # Anti-repetition at the IDEA level, before spending a genotype operation.
        if self.memory.is_explored(t.new_principle, self.config.novelty_threshold):
            self.memory.record(CognitionRecord(
                transformation_id=t.transformation_id, operation=op,
                parent_id=parent.concept_id, rejection_reason="ALREADY_EXPLORED"))
            return None
        self.memory.remember(t)
        return t

    def _execute(self, t, parent, partner, space, rng, program) -> ConceptDNA | None:
        """Hand the transformation to the EXISTING deterministic operator."""
        # EVOLVE may change direction but not identity, so the identity facets are
        # pinned — the same set repair protects via ConceptIdentity. `pinned` is a set
        # of FACET IDS: sacred ONTOLOGY REFS do not belong here (they fail Lineage's
        # facet pattern), and sacred constraints are already enforced upstream by
        # check_constraints and downstream by the critics.
        pinned: set[str] = set(IDENTITY_FACETS) if t.operation is Op.EVOLVE else set()
        if t.operation is Op.HYBRIDISE and partner is not None:
            outcome = op_hybridise(self.ont, space, parent.genotype, partner.genotype,
                                   rng, pinned)
        else:
            outcome = apply_operator(t.genotype_operation, self.ont, space,
                                     parent.genotype, rng, pinned, t.magnitude)

        rec = CognitionRecord(
            transformation_id=t.transformation_id, operation=t.operation,
            parent_id=parent.concept_id, genotype_operation=t.genotype_operation,
            genotype_status=outcome.status, generation=parent.lineage.generation + 1,
            feasibility_risk=t.feasibility_risk,
        )
        if outcome.status != "APPLIED" or outcome.genotype is None:
            self.memory.record(rec.model_copy(update={"rejection_reason": outcome.status}))
            return None

        # Measured with the SAME metric the allocator and Vendi use — cognition does
        # not get its own notion of distance. RECORDED, not gated: the metric is
        # calibrated for whole-portfolio divergence (D_MIN 0.35), and a single-facet
        # operator cannot reach that by construction — spatial_narrative is weighted
        # 0.09 and scale_strategy 0.03, so gating here would silently disable
        # SEQUENCE, SCALE and DISTORT. Near-duplicates are caught where they should
        # be: across the whole pool at stage 11, by is_duplicate.
        rec = rec.model_copy(update={
            "conceptual_distance": round(
                genotype_distance(self.ont, parent.genotype, outcome.genotype), 4),
            "novelty_score": round(t.confidence, 4)})

        child_id = deterministic_id("cn", t.transformation_id)
        child = parent.model_copy(update={
            "concept_id": child_id,
            "genotype": outcome.genotype,
            "status": "DRAFT",
            "evaluation": None,
            "rejection": None,
            # Provenance uses the EXISTING Lineage — no second graph.
            "lineage": Lineage(
                parent_ids=[p for p in (parent.concept_id, t.second_parent_id) if p],
                operator=f"{t.operation.value.lower()}:{t.genotype_operation}",
                magnitude=t.magnitude,
                pinned_facets=sorted(pinned),
                generation=parent.lineage.generation + 1,
                origin="COGNITION",
            ),
        })
        self.memory.record(rec.model_copy(update={"child_concept_id": child_id}))
        return child
