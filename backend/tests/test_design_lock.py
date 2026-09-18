"""The Concept tab and the 3D handoff must describe ONE building, photographed for real.

Before the design lock the two tabs built their descriptions independently, and an
image model given two descriptions drew two different sets: a colonnaded palace in
one, a white space-frame canopy in the other.
"""
import pytest

from app.creative.synthesis import CreativeSynthesizer
from app.domain.brief import DesignBrief
from app.prompt.architectural import AI_LOOK_NEGATIVES, PHOTO_REALISM, ArchitecturalPromptCompiler
from app.prompt.design_lock import LOCK_SECTIONS, build_design_lock, physical
from app.prompt.set_design import compile_set_design
from app.prompt.views import ViewPromptCompiler
from app.providers.llm.mock_synthesis import MockCreativeProvider


@pytest.fixture(scope="module", params=[
    "A Telugu Hindu wedding for 3000 guests in a convention hall in Hyderabad, Chettinad mansion inspired.",
    "A technology conference for 300 people with presentation stage and networking lounge.",
])
def both_tabs(request, container):
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_lock", raw_text=request.param,
                        dimensions_text="60 x 40 m", output_mode="SET_3D")
    rec = container.pipeline.run(brief, k=3, seed=42)
    dna = rec.concepts[0]
    r = CreativeSynthesizer(ont, MockCreativeProvider(ont)).synthesize(
        dna=dna, brief=brief, program=rec.program, seed=42)
    rec.structured[dna.concept_id] = r.concept
    hero = ArchitecturalPromptCompiler(ont).compile(
        dna=dna, concept=r.concept, brief=brief, program=rec.program, constraints=r.constraints)
    views = ViewPromptCompiler().compile_views(
        hero=hero, dna=dna, concept=r.concept, program=rec.program)
    return ont, rec, dna, hero, views, compile_set_design(ont, rec, dna)


def test_both_tabs_carry_the_same_lock_word_for_word(both_tabs):
    ont, rec, dna, hero, views, handoff = both_tabs
    lock = build_design_lock(ont, dna, rec.structured[dna.concept_id], rec.program)
    for name, text, _ in lock.sections:
        assert hero.section(name) == text, f"{name} differs between the lock and the Concept tab"
        assert f"{name}: {text}" in handoff["design_lock"], f"{name} missing from the 3D handoff"


def test_concept_views_and_3d_views_share_one_signature(both_tabs):
    *_, views, handoff = both_tabs
    assert {v.shared_signature for v in views} == {handoff["shared_signature"]}
    assert {v["shared_signature"] for v in handoff["views"]} == {handoff["shared_signature"]}


def test_every_lock_section_is_present(both_tabs):
    *_, hero, _, _ = both_tabs
    for name in ("STRUCTURE", "MATERIALS", "LIGHTING", "PALETTE"):
        assert name in LOCK_SECTIONS and hero.section(name)


def test_concept_prompt_is_a_photograph_not_a_mood(both_tabs):
    *_, hero, _, _ = both_tabs
    style = hero.section("ARCHITECTURAL VISUALIZATION STYLE")
    assert PHOTO_REALISM in style
    for word in ("saturated colour", "crowd mid-celebration", "cinematic", "dramatic"):
        assert word not in style
    assert "cgi" in hero.negative_prompt and "fantasy palace" in hero.negative_prompt


def test_drawings_do_not_inherit_the_photograph(both_tabs):
    *_, views, _ = both_tabs
    drawings = [v for v in views if "orthographic" in v.camera.lower()]
    assert drawings
    for v in drawings:
        assert not v.section("ARCHITECTURAL VISUALIZATION STYLE")
        assert "vanishing point" in v.negative_prompt


def test_3d_views_match_their_deliverable(both_tabs):
    *_, handoff = both_tabs
    by_key = {v["key"]: v for v in handoff["views"]}
    assert {"hero", "clay", "scale_model", "axonometric", "assembly", "front"} <= set(by_key)
    assert PHOTO_REALISM in by_key["hero"]["positive_prompt"]
    assert all(n in by_key["hero"]["negative_prompt"] for n in AI_LOOK_NEGATIVES[:3])
    for key in ("clay", "scale_model", "axonometric", "assembly", "front"):
        assert PHOTO_REALISM not in by_key[key]["positive_prompt"]
    assert "maquette" in by_key["scale_model"]["positive_prompt"]
    assert "vanishing point" in by_key["front"]["negative_prompt"]


@pytest.mark.parametrize("raw, expected", [
    ("The design is a manifestation of the Chettinad language, with a focus on layered thresholds.", ""),
    ("Open flames placed at varying heights to create a sense of depth and intimacy",
     "Open flames placed at varying heights"),
    ("Hundreds of brass lamps line the aisle", "several dozen brass lamps line the aisle"),
    ("A stunning granite plinth; Granite plinth; teak screens", "a granite plinth; teak screens"),
])
def test_physical_keeps_only_what_can_be_built(raw, expected):
    assert physical(raw).lower() == expected.lower()
