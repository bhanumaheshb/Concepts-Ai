"""Semantic isolation, end to end.

Every brief runs the WHOLE pipeline — Design Intelligence, search, cognition, scene,
critics, repair, portfolio, synthesis, Visual Director, compilers — and every artefact
it produces is inspected for vocabulary that belongs to another event.

The word check below is an independent regex, deliberately NOT the engine's own leak
detector, so this suite cannot pass merely because the detector and the generator
share a blind spot.
"""
from __future__ import annotations

import hashlib
import re

import pytest

from app.creative.pipeline import Pipeline
from app.creative.synthesis import CreativeSynthesizer
from app.creative_cognition import CognitionConfig, CreativeCognition
from app.domain.brief import DesignBrief
from app.persistence.repository import InMemoryStore
from app.prompt.architectural import ArchitecturalPromptCompiler
from app.prompt.views import ViewPromptCompiler
from app.providers.llm.mock_cognition import MockCognitionProvider
from app.providers.llm.mock_synthesis import MockCreativeProvider
from app.semantics.knowledge import _is_negated, normalise
from app.semantics.priors import value_out_of_scope

HINDU_RITE_WORDS = [r"mandap\w*", r"agni", r"havan", r"hawan", r"homa kund", r"ritual fire",
                    r"sacred fire", r"varmala", r"jaimala", r"pheras?", r"saptapadi", r"vidaai"]
CEREMONY_WORDS = HINDU_RITE_WORDS + [r"priests?", r"pandit", r"ceremonial (?:centre|center|focus)"]
WEDDING_WORDS = CEREMONY_WORDS + [r"bride\w*", r"groom\w*", r"weddings?", r"nikah", r"altar"]

CASES = {
    "A_sangeet": ("Luxury Sangeet for 500 people in Jaipur with a large dance floor, "
                  "live performance stage and bar.", "sangeet", CEREMONY_WORDS, "performance_stage"),
    "B_haldi": ("200-person Haldi ceremony", "haldi", CEREMONY_WORDS, "haldi_seat"),
    "C_hindu_wedding": ("500-person Hindu wedding mandap", "wedding_ceremony", [], "ceremony_focus"),
    "D_nikah": ("500-person Muslim wedding / Nikah", "wedding_ceremony", HINDU_RITE_WORDS, "ceremony_focus"),
    "E_christian": ("500-person Christian wedding", "wedding_ceremony", HINDU_RITE_WORDS, "ceremony_focus"),
    "F_concert": ("1000-person music concert", "music_concert", WEDDING_WORDS, "performance_stage"),
    "G_launch": ("300-person corporate product launch", "product_launch", WEDDING_WORDS, "reveal_zone"),
    "H_runway": ("A fashion runway show for 250 guests with backstage and press",
                 "fashion_show", WEDDING_WORDS, "runway"),
    "I_restaurant": ("A futuristic restaurant interior for 60 covers, moderate budget.",
                     "restaurant", WEDDING_WORDS, "dining"),
    "J_unknown": ("An immersive astronomy storytelling night for 350 people in Hyderabad with "
                  "projection surfaces, live narration and informal seating.",
                  "immersive_astronomy_storytelling_night", WEDDING_WORDS, "projection_field"),
}


def affirmed_hits(patterns: list[str], text: str) -> list[str]:
    """Positive mentions only: 'no mandap' in a negative list is the prompt doing its job."""
    t = normalise(text)
    out = []
    for pat in patterns:
        for m in re.finditer(rf"(?<![a-z]){pat}(?![a-z])", t):
            if not _is_negated(t, m.start()):
                out.append(m.group(0))
    return out


@pytest.fixture(scope="module")
def runs(container, ont):
    pipeline = Pipeline(
        ont, container.llm, InMemoryStore(), use_llm_critics=False,
        synthesizer=CreativeSynthesizer(ont, MockCreativeProvider(ont)),
        arch_compiler=ArchitecturalPromptCompiler(ont), view_compiler=ViewPromptCompiler(),
        cognition=CreativeCognition(ont, MockCognitionProvider(), CognitionConfig()))
    out = {}
    for name, (text, *_rest) in CASES.items():
        bid = "bf_" + hashlib.sha1(text.encode()).hexdigest()[:10]
        out[name] = pipeline.run(DesignBrief(brief_id=bid, raw_text=text), k=3, seed=42)
    return out


@pytest.mark.parametrize("name", list(CASES))
def test_run_completes_as_the_requested_event(runs, name):
    rec = runs[name]
    _, event, _, focus = CASES[name]
    assert rec.status == "COMPLETE", rec.error
    assert rec.concepts, "no concept survived"
    assert rec.semantic.profile.identity.event_type == event
    assert rec.semantic.intent.primary_zone_key == focus
    assert rec.stage_runs[0].stage == "01" and rec.stage_runs[0].label == "Design intelligence"


@pytest.mark.parametrize("name", list(CASES))
def test_no_foreign_vocabulary_in_any_artefact(runs, name):
    rec = runs[name]
    words = CASES[name][2]
    if not words:
        pytest.skip("a Hindu wedding may use its own rite's vocabulary")
    for c in rec.concepts:
        ph = c.phenotype
        texts = {
            "phenotype": " ".join([ph.title, ph.one_line, ph.design_thesis, ph.spatial_explanation,
                                   ph.material_explanation, ph.experience_narrative]),
            "scene": " ".join(n.role or "" for n in rec.scenes[c.concept_id].nodes).replace("_", " "),
            "hero_prompt": rec.arch_prompts[c.concept_id].positive_prompt,
            "views": " ".join(v.positive_prompt for v in rec.view_prompts[c.concept_id]),
            "visual_intents": " ".join(
                " ".join([i.visual_subject, i.story_of_image, i.foreground, i.midground,
                          i.background, i.human_activity, i.primary_focal_point,
                          " ".join(i.visible_program_zones), " ".join(i.important_elements)])
                for i in rec.visual_intents[c.concept_id]),
        }
        if c.concept_id in rec.structured:
            texts["structured_concept"] = rec.structured[c.concept_id].model_dump_json()
        for where, text in texts.items():
            hits = affirmed_hits(words, text)
            assert not hits, f"{name}: {where} of {c.phenotype.title} mentions {sorted(set(hits))}"


@pytest.mark.parametrize("name", list(CASES))
def test_genotypes_stay_inside_semantic_scope(runs, name, ont):
    rec = runs[name]
    for c in rec.concepts + rec.rejected:
        for ref in c.genotype.all_refs():
            node = ont.nodes.get(ref)
            assert not (node and value_out_of_scope(node, rec.semantic)), f"{name}: {ref}"


@pytest.mark.parametrize("name", list(CASES))
def test_required_programme_is_built_and_critic_agrees(runs, name):
    rec = runs[name]
    required = {z.key for z in rec.semantic.programme if z.priority == "required"}
    for c in rec.concepts:
        zones = {n.role for n in rec.scenes[c.concept_id].by_type("zone")}
        assert required <= zones, f"{name}: missing {required - zones}"
        assert c.evaluation.semantic is not None and c.evaluation.semantic.passed


@pytest.mark.parametrize("name", list(CASES))
def test_prompt_subject_and_visual_intent_name_this_event(runs, name):
    rec = runs[name]
    label = rec.semantic.profile.identity.event_type_label
    focus = rec.semantic.primary_zone()
    for c in rec.concepts:
        hero = rec.arch_prompts[c.concept_id]
        assert label.lower() in hero.section("SUBJECT").lower()
        assert hero.section("IMAGE STORY") and hero.section("HUMAN ACTIVITY")
        assert not hero.semantic_leaks
        intents = rec.visual_intents[c.concept_id]
        hero_i = next(i for i in intents if i.view_key == "hero")
        assert hero_i.primary_focal_point == focus.label
        assert hero_i.human_activity
        # the shot list IS the programme: every rendered view is a real zone or a drawing
        zone_keys = {z.key for z in rec.semantic.programme}
        for v in rec.view_prompts[c.concept_id]:
            base = v.view_key.split("__")[0]
            assert base in zone_keys or base.startswith("drawing_"), v.view_key


def test_sangeet_hero_communicates_performance_not_ceremony(runs):
    rec = runs["A_sangeet"]
    for c in rec.concepts:
        hero = rec.arch_prompts[c.concept_id]
        story = hero.section("IMAGE STORY").lower() + hero.section("HUMAN ACTIVITY").lower()
        assert "danc" in story and ("perform" in story or "stage" in story)
        neg = hero.negative_prompt.lower()
        assert "mandap" in neg and "ritual fire" in neg     # near-miss confusions are pushed away


def test_haldi_and_sangeet_are_different_programmes(runs):
    a, b = runs["A_sangeet"].semantic, runs["B_haldi"].semantic
    assert {z.key for z in a.programme} != {z.key for z in b.programme}
    assert a.profile.audience_relationship == b.profile.audience_relationship == "participatory"
    assert a.intent.must_communicate != b.intent.must_communicate


def test_product_launch_and_concert_differ_in_programme_and_visual_logic(runs):
    launch, concert = runs["G_launch"], runs["F_concert"]
    assert "reveal_zone" in {z.key for z in launch.semantic.programme}
    assert "audience_field" in {z.key for z in concert.semantic.programme}
    li = next(i for i in launch.visual_intents[launch.concepts[0].concept_id] if i.view_key == "hero")
    ci = next(i for i in concert.visual_intents[concert.concepts[0].concept_id] if i.view_key == "hero")
    assert li.primary_focal_point != ci.primary_focal_point


def test_hindu_wedding_keeps_its_ritual(runs):
    rec = runs["C_hindu_wedding"]
    assert rec.program.ritual and "ritual:agni_kund" in rec.program.ritual.required_elements
    assert any(c.sacred and c.constraint_id == "c_ritual_agni" for c in rec.program.invariants)
    hero = rec.arch_prompts[rec.concepts[0].concept_id]
    assert "mandap" in hero.section("FOCAL POINT").lower()


def test_unknown_event_runs_without_a_catalogue_entry(runs):
    rec = runs["J_unknown"]
    assert not rec.semantic.profile.identity.known_type
    views = {v.view_key for v in rec.view_prompts[rec.concepts[0].concept_id]}
    assert {"projection_field", "narrator_position", "informal_seating"} <= views


def test_llm_trace_and_stage_detail_are_recorded(runs):
    rec = runs["A_sangeet"]
    labels = [s.label for s in rec.stage_runs]
    assert "Design intelligence" in labels and "Visual direction" in labels
    detail = next(s.detail for s in rec.stage_runs if s.stage == "01")
    assert "Sangeet" in detail and "forbidden" in detail
    assert rec.semantic.reasoner.source == "DETERMINISTIC"     # mock suite: no model
