"""End-to-end divergence tests — the acceptance criterion for the vertical slice."""
from collections import Counter

import pytest

from app.creative.pipeline import Pipeline
from app.diversity.metric import D_MIN
from app.domain.brief import DesignBrief
from app.persistence.repository import InMemoryStore

BRIEFS = [
    ("mandap", "Create a luxury Indian wedding mandap for 500 guests.", "Jaipur, May"),
    ("restaurant", "A futuristic restaurant interior for 60 covers, moderate budget.", "Mumbai"),
    ("pavilion", "An experimental exhibition pavilion, 24x16 m, for 300 visitors.", "Berlin"),
]
SEEDS = (42, 7, 1234)
TARGET = {"CANONICAL": 1, "ADJACENT": 3, "EXPLORATORY": 4, "RADICAL": 1, "WILDCARD": 1}


@pytest.fixture(scope="module")
def engine(container):
    """A pipeline with its OWN store.

    These are acceptance thresholds, and the novelty archive steers the allocator — so
    sharing the session container let whatever ran earlier (notably the API tests, whose
    explorations land in the same archive) decide whether a threshold was met. The
    pavilion case failed in a full-suite run and passed in isolation for exactly this
    reason. The archive here contains only this module's own runs.
    """
    return Pipeline(container.ontology, container.llm, InMemoryStore(),
                    use_llm_critics=container.settings.mock_critic_policy
                    != "deterministic_only")


def _run(engine, name, text, loc, seed):
    brief = DesignBrief(brief_id=f"bf_{name}_{seed}", raw_text=text, location=loc)
    return engine.run(brief, k=10, seed=seed)


@pytest.mark.parametrize("name,text,loc", BRIEFS)
@pytest.mark.parametrize("seed", SEEDS)
def test_portfolio_shape_and_divergence(engine, name, text, loc, seed):
    rec = _run(engine, name, text, loc, seed)
    assert rec.status == "COMPLETE", rec.error
    assert len(rec.concepts) == 10

    # 1 canonical / 3 adjacent / 4 exploratory / 1 radical / 1 wildcard
    assert Counter(c.role.value for c in rec.concepts) == TARGET

    m = rec.matrix
    assert m.min_pairwise >= D_MIN, f"duplicate pair at {m.min_pairwise}"
    assert m.mean_pairwise >= 0.55
    assert m.vendi_score >= 6.5, f"portfolio collapsed to {m.vendi_score} effective concepts"

    # every concept passed all four gates and carries a compiled prompt
    for c in rec.concepts:
        assert c.evaluation and c.evaluation.gate_passed
        assert c.evaluation.cultural.passed
        pc = rec.prompts[c.concept_id]
        assert pc.positive_prompt and pc.negative_prompt and pc.prompt_hash


@pytest.mark.parametrize("name,text,loc", BRIEFS)
def test_concepts_are_conceptually_not_merely_visually_different(engine, name, text, loc):
    rec = _run(engine, name, text, loc, 42)
    langs = {c.genotype.architectural_language.value for c in rec.concepts}
    geoms = {c.genotype.geometry.system for c in rec.concepts}
    structs = {c.genotype.structural_logic.value for c in rec.concepts}
    mats = {c.genotype.primary_material().material for c in rec.concepts}
    assert len(langs) >= 8, langs
    assert len(geoms) >= 7, geoms
    assert len(structs) >= 7, structs
    assert len(mats) >= 6, mats


def test_same_seed_is_reproducible(engine):
    a = _run(engine, "repro", BRIEFS[0][1], BRIEFS[0][2], 42)
    b = _run(engine, "repro", BRIEFS[0][1], BRIEFS[0][2], 42)
    assert [c.genotype.model_dump() for c in a.concepts] == [c.genotype.model_dump() for c in b.concepts]
    assert ([a.prompts[c.concept_id].prompt_hash for c in a.concepts]
            == [b.prompts[c.concept_id].prompt_hash for c in b.concepts])


def test_different_seeds_give_different_portfolios(engine):
    """Guards the opposite failure: reproducible because it always returns the same ten."""
    a = _run(engine, "vary", BRIEFS[0][1], BRIEFS[0][2], 42)
    b = _run(engine, "vary", BRIEFS[0][1], BRIEFS[0][2], 4242)
    titles_a = {c.phenotype.title for c in a.concepts}
    titles_b = {c.phenotype.title for c in b.concepts}
    genos_a = {c.genotype.model_dump_json() for c in a.concepts}
    genos_b = {c.genotype.model_dump_json() for c in b.concepts}
    assert genos_a != genos_b
    assert len(titles_a & titles_b) < 8


def test_rationale_chains_cite_real_constraints(engine):
    rec = _run(engine, "rat", BRIEFS[0][1], BRIEFS[0][2], 42)
    valid = rec.program.constraint_ids()
    for c in rec.concepts:
        assert len(c.phenotype.rationale_chain) >= 3
        for link in c.phenotype.rationale_chain:
            assert link.evidence_ref in valid or link.evidence_ref.startswith("program.")


def test_scene_graphs_are_dimensioned(engine):
    rec = _run(engine, "scene", BRIEFS[0][1], BRIEFS[0][2], 42)
    for c in rec.concepts:
        sg = rec.scenes[c.concept_id]
        assert sg.status in ("COMPLETE", "PARTIAL")
        zones = sg.by_type("zone")
        assert zones and all(z.width_m and z.depth_m for z in zones)
        assert sg.derived.total_zone_area_m2 > 0
        assert sg.node("camera_hero") is not None


def test_pipeline_records_every_stage(engine):
    rec = _run(engine, "stages", BRIEFS[0][1], BRIEFS[0][2], 42)
    assert len(rec.stage_runs) == 15
    assert all(s.status == "OK" for s in rec.stage_runs)
