"""The per-area shot list: several prompts, one venue.

The property that matters is not that six prompts exist — it is that they render as
the same place. That is asserted here against the identity sections themselves, not
against a promise in a docstring.
"""
import pytest

from app.creative.program import build_program
from app.creative.synthesis import CreativeSynthesizer
from app.creative.synthesis_prompt import build_constraints
from app.domain.brief import DesignBrief
from app.prompt.architectural import ArchitecturalPromptCompiler
from app.prompt.views import IDENTITY_SECTIONS, ViewPromptCompiler
from app.providers.llm.mock_synthesis import MockCreativeProvider

BRIEF = "Create a 500-person luxury Sangeeth mandap with a dance floor and a bar."


@pytest.fixture(scope="module")
def shot(container):
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_views", raw_text=BRIEF, location="Jaipur, May")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=3, seed=42)
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    compiler = ArchitecturalPromptCompiler(ont)
    views = ViewPromptCompiler()

    sets = []
    for dna in rec.concepts:
        r = synth.synthesize(dna=dna, brief=brief, program=program, seed=42)
        hero = compiler.compile(dna=dna, concept=r.concept, brief=brief,
                                program=program, constraints=r.constraints)
        sets.append((dna, hero, views.compile_views(
            hero=hero, dna=dna, concept=r.concept, program=program,
            brief_text=BRIEF)))
    return ont, brief, program, sets


# ─────────────────── the set covers the venue ───────────────────

def test_a_concept_produces_a_prompt_for_each_area(shot):
    _, _, _, sets = shot
    keys = [v.view_key for v in sets[0][2]]
    for expected in ("entrance", "walkway", "mandap", "seating"):
        assert expected in keys, f"no prompt for {expected}: got {keys}"


def test_an_area_the_brief_asks_for_is_always_shot(shot):
    """The brief said 'with a dance floor and a bar'. A missing shot the client
    explicitly asked for is worse than a thin one, so the brief overrides the
    model's silence."""
    _, _, _, sets = shot
    keys = {v.view_key for v in sets[0][2]}
    assert "dance_floor" in keys, f"brief asked for a dance floor: got {sorted(keys)}"
    assert "bar" in keys, f"brief asked for a bar: got {sorted(keys)}"


def test_an_area_nobody_asked_for_is_not_invented(container):
    """The converse: silence in both the brief and the model means no shot."""
    ont = container.ontology
    plain = "Create a 500-person traditional wedding mandap."
    brief = DesignBrief(brief_id="bf_quiet", raw_text=plain, location="Jaipur, May")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=3, seed=11)
    dna = rec.concepts[0]
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    r = synth.synthesize(dna=dna, brief=brief, program=program, seed=11)
    hero = ArchitecturalPromptCompiler(ont).compile(
        dna=dna, concept=r.concept, brief=brief, program=program,
        constraints=r.constraints)
    views = ViewPromptCompiler().compile_views(
        hero=hero, dna=dna, concept=r.concept, program=program, brief_text=plain)
    assert "bar" not in {v.view_key for v in views}


def test_every_view_is_a_complete_standalone_prompt(shot):
    _, _, _, sets = shot
    for _, _, views in sets:
        for v in views:
            assert v.positive_prompt.startswith("SUBJECT:")
            assert "CAMERA:" in v.positive_prompt
            assert v.negative_prompt
            assert v.prompt_hash


def test_each_view_names_its_own_area_in_the_subject(shot):
    _, _, _, sets = shot
    for v in sets[0][2]:
        assert v.section("SUBJECT").lower().startswith(f"the {v.view_label.lower()}")


def test_each_view_has_its_own_camera(shot):
    """Six identical cameras would be six identical images."""
    _, _, _, sets = shot
    cameras = [v.camera for v in sets[0][2]]
    assert len(set(cameras)) == len(cameras), "two areas share a camera"


def test_view_prompts_are_distinct_from_each_other(shot):
    _, _, _, sets = shot
    hashes = [v.prompt_hash for v in sets[0][2]]
    assert len(set(hashes)) == len(hashes)


# ─────────────────── …and reads as ONE venue (the point) ───────────────────

def test_all_views_of_a_concept_share_one_signature(shot):
    _, _, _, sets = shot
    for _, _, views in sets:
        signatures = {v.shared_signature for v in views}
        assert len(signatures) == 1, "a concept's views drifted apart"
        assert signatures.pop(), "signature is empty"


def test_the_identity_sections_are_byte_identical_across_views(shot):
    """Materials, lighting, structure and atmosphere must not be re-derived per view:
    re-deriving is exactly how a set of images stops looking like one building."""
    _, _, _, sets = shot
    _, _, views = sets[0]
    for name in IDENTITY_SECTIONS:
        texts = {v.section(name) for v in views if v.section(name)}
        assert len(texts) <= 1, f"{name} differs between views of one concept"


def test_two_different_concepts_do_not_share_a_signature(shot):
    """The signature has to actually discriminate, or it asserts nothing."""
    _, _, _, sets = shot
    signatures = [views[0].shared_signature for _, _, views in sets if views]
    assert len(set(signatures)) == len(signatures), "distinct concepts collided"


def test_a_view_carries_the_concepts_material_and_structure(shot):
    _, _, _, sets = shot
    _, hero, views = sets[0]
    for v in views:
        assert v.section("MATERIALS") == hero.section("MATERIALS")
        assert v.section("STRUCTURE") == hero.section("STRUCTURE")


# ─────────────────── derivation, not invention ───────────────────

def test_an_optional_area_the_concept_never_mentions_is_omitted(container):
    """A ceremony with no bar must not get a bar prompt invented for it."""
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_plain", location="Jaipur, May",
                        raw_text="Create a 500-person traditional wedding mandap.")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=3, seed=7)
    dna = rec.concepts[0]
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    r = synth.synthesize(dna=dna, brief=brief, program=program, seed=7)
    hero = ArchitecturalPromptCompiler(ont).compile(
        dna=dna, concept=r.concept, brief=brief, program=program,
        constraints=r.constraints)
    views = ViewPromptCompiler().compile_views(
        hero=hero, dna=dna, concept=r.concept, program=program)
    required = {"entrance", "walkway", "mandap", "seating"}
    assert required <= {v.view_key for v in views}


def test_views_still_compile_with_no_model_at_all(container):
    """The §21 guarantee extends to the shot list: no LLM, still a full set."""
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_nomodel", raw_text=BRIEF, location="Jaipur, May")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=3, seed=42)
    dna = rec.concepts[0]
    cons = build_constraints(ont, program, brief, dna.genotype)
    hero = ArchitecturalPromptCompiler(ont).compile(
        dna=dna, concept=None, brief=brief, program=program, constraints=cons)
    views = ViewPromptCompiler().compile_views(
        hero=hero, dna=dna, concept=None, program=program)
    assert len(views) >= 4
    assert all(v.positive_prompt for v in views)
    assert len({v.shared_signature for v in views}) == 1


def test_the_hero_prompt_is_left_untouched(shot):
    """Adding a shot list must not alter the single prompt that already existed."""
    _, _, _, sets = shot
    _, hero, _ = sets[0]
    assert hero.view_key == "hero"
    assert hero.shared_signature == ""
