"""Creative Cognition.

The layer proposes conceptual moves; the deterministic engine executes and verifies
them. These tests assert that division: cognition may ADD candidates and rejection
reasons, and may never mutate a genotype itself, invert a hard constraint, or change
anything at all while disabled.
"""
from __future__ import annotations

import pytest

from app.creative.pipeline import Pipeline
from app.creative_cognition import CognitionConfig, CreativeCognition
from app.creative_cognition.memory import CreativeMemory, _signature
from app.creative_cognition.operators import (
    CognitionContext, check_constraints, genotype_op_for, magnitude_for,
)
from app.domain.brief import DesignBrief
from app.domain.cognition import (
    CognitiveOperation as Op, CreativeTransformation, FeasibilityRisk,
)
from app.mutation.operators import REGISTRY
from app.providers.llm.mock_cognition import MockCognitionProvider

BRIEF = "Create a luxury Indian wedding mandap for 500 guests."
LOC = "Jaipur, May"


def _brief(bid="bf_cog"):
    return DesignBrief(brief_id=bid, raw_text=BRIEF, location=LOC)


def _cognition(container, **cfg):
    return CreativeCognition(container.ontology, MockCognitionProvider(),
                             CognitionConfig(**cfg))


def _pipeline(container, cognition=None):
    return Pipeline(container.ontology, container.llm, container.store,
                    use_llm_critics=False, cognition=cognition)


@pytest.fixture(scope="module")
def plain(container):
    return _pipeline(container).run(_brief(), k=10, seed=42)


@pytest.fixture(scope="module")
def enabled(container):
    cog = _cognition(container, budget=10)
    rec = _pipeline(container, cog).run(_brief("bf_cog_on"), k=10, seed=42)
    return rec, cog


# ── 1. disabled mode is a true no-op ─────────────────────────────────────────

def test_disabled_produces_no_cognition_stage_and_no_cognition_concepts(plain):
    stages = {s.stage for s in plain.stage_runs}
    assert "08c" not in stages and "09c" not in stages
    assert all(c.lineage.origin != "COGNITION" for c in plain.all_concepts())
    assert plain.cognition is None


def test_disabled_matches_a_pipeline_built_without_the_argument(container):
    """The feature flag must not perturb the engine even structurally."""
    a = _pipeline(container).run(_brief("bf_same"), k=10, seed=42)
    b = Pipeline(container.ontology, container.llm, container.store,
                 use_llm_critics=False).run(_brief("bf_same"), k=10, seed=42)
    assert [c.genotype.model_dump(mode="json") for c in a.concepts] \
        == [c.genotype.model_dump(mode="json") for c in b.concepts]


def test_default_settings_keep_cognition_off():
    from app.core.config import Settings
    assert Settings().creative_cognition_enabled is False


# ── 2. determinism ───────────────────────────────────────────────────────────

def test_same_seed_produces_identical_cognition(container):
    out = []
    for _ in range(2):
        cog = _cognition(container, budget=8)
        rec = _pipeline(container, cog).run(_brief("bf_det"), k=10, seed=7)
        out.append(([c.genotype.model_dump(mode="json") for c in rec.concepts],
                    [r.transformation_id for r in cog.memory.records]))
    assert out[0] == out[1]


def test_a_different_seed_explores_differently(container):
    ids = []
    for seed in (42, 99):
        cog = _cognition(container, budget=8)
        _pipeline(container, cog).run(_brief("bf_seed"), k=10, seed=seed)
        ids.append([r.operation.value for r in cog.memory.records
                    if r.genotype_status == "APPLIED"])
    assert ids[0] != ids[1] or len(ids[0]) != len(ids[1])


# ── 3-11. the operators ──────────────────────────────────────────────────────

def _context(rec, container, **kw):
    return CognitionContext(concept=rec.concepts[0], program=rec.program,
                            antibrief=rec.antibrief, **kw)


@pytest.mark.parametrize("op,expected", [
    (Op.REINTERPRET, "reinterpret"),
    (Op.INVERT, "invert"),
    (Op.DISTORT, "attenuate"),
    (Op.REMOVE, "remove"),
    (Op.SCALE, "scale_up"),
    (Op.SEQUENCE, "resequence"),
    (Op.ASSOCIATE, "reinterpret"),
])
def test_every_operation_dispatches_to_an_existing_registry_operator(op, expected):
    """Cognition must REUSE the mutation registry, never reimplement it."""
    assert genotype_op_for(op) == expected
    assert expected in REGISTRY, f"{expected} is not a registered genotype operator"


def test_distort_is_actually_pushed(plain):
    """A distortion at default magnitude is just a variant."""
    assert magnitude_for(Op.DISTORT) >= 0.75
    assert magnitude_for(Op.SCALE) < magnitude_for(Op.DISTORT)


def test_reinterpret_changes_the_genotype_not_only_the_words(container, plain):
    cog = _cognition(container, budget=4, enabled_operations=(Op.REINTERPRET,))
    out = cog.expand(concepts=plain.concepts[:3], program=plain.program,
                     antibrief=plain.antibrief, space=plain.space,
                     exploration_id="ex_re", seed=42)
    children = [c for c in out if c.lineage.origin == "COGNITION"]
    assert children, "reinterpret produced nothing"
    for ch in children:
        parent = next(p for p in plain.concepts if p.concept_id in ch.lineage.parent_ids)
        assert ch.genotype != parent.genotype


def test_sequence_reorders_the_spatial_narrative(container, plain):
    cog = _cognition(container, budget=6, enabled_operations=(Op.SEQUENCE,))
    out = cog.expand(concepts=plain.concepts[:4], program=plain.program,
                     antibrief=plain.antibrief, space=plain.space,
                     exploration_id="ex_seq", seed=42)
    children = [c for c in out if c.lineage.origin == "COGNITION"]
    assert children
    for ch in children:
        parent = next(p for p in plain.concepts if p.concept_id in ch.lineage.parent_ids)
        assert set(ch.genotype.spatial_narrative) == set(parent.genotype.spatial_narrative)
        assert list(ch.genotype.spatial_narrative) != list(parent.genotype.spatial_narrative)


def test_remove_drops_a_beat_without_emptying_the_sequence(container, plain):
    cog = _cognition(container, budget=6, enabled_operations=(Op.REMOVE,))
    out = cog.expand(concepts=plain.concepts[:4], program=plain.program,
                     antibrief=plain.antibrief, space=plain.space,
                     exploration_id="ex_rm", seed=42)
    children = [c for c in out if c.lineage.origin == "COGNITION"]
    assert children
    for ch in children:
        parent = next(p for p in plain.concepts if p.concept_id in ch.lineage.parent_ids)
        assert len(ch.genotype.spatial_narrative) == len(parent.genotype.spatial_narrative) - 1
        assert len(ch.genotype.spatial_narrative) >= 1


def test_hybridise_records_two_parents(container, plain):
    cog = _cognition(container, budget=4, enabled_operations=(Op.HYBRIDISE,))
    out = cog.expand(concepts=plain.concepts[:6], program=plain.program,
                     antibrief=plain.antibrief, space=plain.space,
                     exploration_id="ex_hy", seed=42)
    children = [c for c in out if c.lineage.origin == "COGNITION"]
    assert children
    assert any(len(c.lineage.parent_ids) == 2 for c in children)


def test_associate_uses_the_supplied_abstracted_principle(container, plain):
    ctx = _context(plain, container,
                   principle_statements=("descent is the arrival sequence",))
    rendered = ctx.render(Op.ASSOCIATE)
    assert "descent is the arrival sequence" in rendered
    assert "map the relationship" in rendered.lower() or "TRANSFERABLE PRINCIPLE" in rendered


def test_evolve_routes_through_the_existing_repair_route():
    from app.critics import codes
    assert genotype_op_for(Op.EVOLVE, (codes.FEAS_SPAN_EXCEEDED,)) == "material_substitute"
    assert genotype_op_for(Op.EVOLVE, ()) in REGISTRY


# ── 12. hard constraints ─────────────────────────────────────────────────────

def test_invert_is_never_offered_a_blocked_assumption(plain, container):
    ctx = _context(plain, container)
    offered = ctx.assumptions()
    blocked = [a.statement for a in plain.antibrief.questioned_assumptions
               if a.blocked_by is not None]
    assert blocked, "fixture has no blocked assumption to test against"
    for b in blocked:
        assert b not in offered


def test_a_transformation_touching_a_sacred_constraint_is_rejected(container):
    """Stabilisation made the rite tradition-specific, so a brief that names no
    tradition correctly has NO sacred invariant. Select one explicitly."""
    from app.domain.common import EventType, Tradition, Typology
    from app.creative.program import build_program
    b = DesignBrief(brief_id="bf_sacred", raw_text=BRIEF, location=LOC,
                    typology=Typology.WEDDING_MANDAP, event_type=EventType.WEDDING,
                    tradition=Tradition.HINDU)
    program = build_program(container.ontology, b)
    sacred = next((c for c in program.invariants if c.sacred), None)
    assert sacred is not None, "HINDU wedding must carry a sacred invariant"
    t = CreativeTransformation(
        transformation_id="t1", operation=Op.INVERT, source_concept_id="cn_x",
        assumption_or_principle=sacred.statement,
        transformation="remove it entirely",
        new_principle=sacred.statement,
        spatial_or_design_consequence="the rite is abandoned")
    checked = check_constraints(t, program)
    assert checked.feasibility_risk is FeasibilityRisk.REJECTED
    assert sacred.constraint_id in checked.constraint_violations
    assert checked.executable is False


def test_rejected_transformations_never_reach_the_genotype(container, plain):
    """A REJECTED idea is recorded for the trace and never executed."""
    cog = _cognition(container, budget=6)
    cog.expand(concepts=plain.concepts[:3], program=plain.program,
               antibrief=plain.antibrief, space=plain.space,
               exploration_id="ex_rej", seed=42)
    for r in cog.memory.records:
        if r.feasibility_risk is FeasibilityRisk.REJECTED:
            assert r.child_concept_id is None


# ── 13. anti-repetition ──────────────────────────────────────────────────────

def test_memory_detects_the_same_idea_in_different_words():
    m = CreativeMemory()
    t = CreativeTransformation(
        transformation_id="t", operation=Op.REINTERPRET, source_concept_id="c",
        assumption_or_principle="circulation is a corridor",
        transformation="it becomes the gathering volume",
        new_principle="circulation becomes the primary social gathering volume",
        spatial_or_design_consequence="movement and gathering share one volume")
    m.remember(t)
    assert m.is_explored("circulation becomes the primary social gathering volume")
    assert m.is_explored("the primary social gathering volume becomes circulation")
    assert not m.is_explored("the roof is carried on a single central mast")


def test_signature_ignores_filler_words():
    assert _signature("the space becomes a design concept") == frozenset()


def test_already_explored_is_recorded_as_a_rejection(enabled):
    _, cog = enabled
    reasons = {r.rejection_reason for r in cog.memory.records if r.rejection_reason}
    assert any("ALREADY_EXPLORED" in x for x in reasons)


# ── 14. provenance ───────────────────────────────────────────────────────────

def test_every_cognition_concept_is_traceable(enabled):
    """Provenance is Lineage plus the cognition memory. The parent OBJECT may be
    absent from the record: the existing pipeline keeps only selected and rejected
    concepts, so an unselected parent is dropped — which predates this layer."""
    rec, cog = enabled
    children = [c for c in rec.all_concepts() if c.lineage.origin == "COGNITION"]
    assert children, "cognition produced no concepts to trace"
    edges = {r.child_concept_id: r for r in cog.memory.records if r.child_concept_id}
    for ch in children:
        assert ch.lineage.parent_ids
        assert ch.lineage.operator and ":" in ch.lineage.operator
        assert ch.lineage.generation >= 1
        rec_edge = edges.get(ch.concept_id)
        assert rec_edge is not None, f"{ch.concept_id} has no cognition record"
        assert rec_edge.parent_id in ch.lineage.parent_ids
        assert (rec_edge.genotype_operation in REGISTRY
                or rec_edge.genotype_operation == "hybridise")


def test_lineage_operator_names_both_layers(enabled):
    """conceptual_operation:genotype_operator — so the trace says WHY and HOW."""
    rec, _ = enabled
    for c in rec.all_concepts():
        if c.lineage.origin == "COGNITION":
            concept_op, geno_op = c.lineage.operator.split(":", 1)
            assert concept_op.upper() in {o.value for o in Op}
            assert geno_op in REGISTRY or geno_op == "hybridise"


# ── 15-19. the existing engine still runs ────────────────────────────────────

def test_cognition_candidates_enter_the_existing_engine(enabled):
    rec, _ = enabled
    stages = {s.stage: s for s in rec.stage_runs}
    assert "08c" in stages
    assert stages["09"].status == "OK"          # critics ran on the expanded set
    assert stages["11"].status == "OK"          # Vendi ran
    assert stages["12"].status == "OK"          # portfolio selected
    assert rec.matrix is not None and rec.matrix.vendi_score > 0


def test_cognition_only_adds_candidates(plain, enabled):
    rec, _ = enabled
    assert len(rec.all_concepts()) > len(plain.concepts)
    assert len(rec.concepts) == len(plain.concepts) == 10


def test_critics_evaluated_every_cognition_child(enabled):
    rec, _ = enabled
    for c in rec.all_concepts():
        if c.lineage.origin == "COGNITION":
            assert c.evaluation is not None, "a cognition child skipped the critics"


def test_portfolio_and_curriculum_still_hold(enabled):
    rec, _ = enabled
    assert rec.portfolio is not None
    assert len(rec.concepts) == 10
    assert rec.matrix.min_pairwise > 0


def test_memory_reports_what_survived(enabled):
    rec, cog = enabled
    s = cog.memory.summary()
    assert s["proposed"] >= s["applied"] >= s["selected"]
    assert set(s["by_operation"]) <= {o.value for o in Op}


# ── 20. quality: different design LOGIC, not different wording ───────────────

def test_expansion_changes_organisation_not_only_material(container, plain):
    """The success criterion: cognition children must differ from their parent in
    how the space is ORGANISED — staging, sequence, structure or scale — and not
    merely in what it is made of."""
    cog = _cognition(container, budget=12)
    out = cog.expand(concepts=plain.concepts[:6], program=plain.program,
                     antibrief=plain.antibrief, space=plain.space,
                     exploration_id="ex_q", seed=42)
    children = [c for c in out if c.lineage.origin == "COGNITION"]
    assert children

    # Everything a designer would call a different IDEA: how the space is organised,
    # how it is built, how it is lit, how it feels. Deliberately excludes
    # material_palette — a child that differs ONLY in what it is made of is the
    # "stone courtyard / marble courtyard / brick courtyard" failure this guards.
    CONCEPTUAL = ("occupation_staging", "spatial_narrative", "structural_logic",
                  "scale_strategy", "geometry_system", "site_relationship",
                  "lighting_philosophy", "tectonic_logic", "emotional_register",
                  "architectural_language", "thesis_archetype")
    restyled = []
    for ch in children:
        parent = next(p for p in plain.concepts if p.concept_id in ch.lineage.parent_ids)
        changed = [f for f in CONCEPTUAL
                   if (list(ch.genotype.spatial_narrative) if f == "spatial_narrative"
                       else ch.genotype.facet_value(f))
                   != (list(parent.genotype.spatial_narrative) if f == "spatial_narrative"
                       else parent.genotype.facet_value(f))]
        if not changed:
            restyled.append(ch.lineage.operator)
    assert not restyled, (
        f"{len(restyled)}/{len(children)} children differ only in material or wording, "
        f"not in design logic: {restyled}")


def test_the_portfolio_spans_several_organisational_strategies(container, plain):
    """SAME BRIEF -> DIFFERENT DESIGN LOGICS. The expanded population must reach
    several distinct occupation strategies, not one strategy in several materials."""
    cog = _cognition(container, budget=12)
    out = cog.expand(concepts=plain.concepts[:6], program=plain.program,
                     antibrief=plain.antibrief, space=plain.space,
                     exploration_id="ex_span", seed=42)
    strategies = {c.genotype.occupation_staging.value for c in out}
    sequences = {tuple(c.genotype.spatial_narrative) for c in out}
    assert len(strategies) >= 3, f"only {len(strategies)} occupation strategies: {strategies}"
    assert len(sequences) >= 4, f"only {len(sequences)} distinct journeys"
