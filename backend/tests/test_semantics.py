"""Design Intelligence — the deterministic reading of a brief.

These assert STRUCTURED state: identity, activities, programme zones, element
statuses, invariants and provenance. Nothing here depends on prose.
"""
from __future__ import annotations

import shutil

import pytest

from app.domain.brief import DesignBrief
from app.domain.common import EventType, Tradition, Typology
from app.domain.semantics import ElementStatus as S, Provenance as P
from app.semantics.intelligence import DesignIntelligence
from app.semantics.knowledge import ROOT, Knowledge, load_knowledge

HINDU_RITE = {"mandap", "ritual_fire", "varmala_platform", "pheras_circuit", "vidaai"}


def read(text: str, **kw):
    brief = DesignBrief(brief_id="bf_t", raw_text=text, **kw)
    from app.creative.program import estimate_capacity
    return DesignIntelligence().understand(brief, capacity=estimate_capacity(brief))


def status(sb, key):
    e = sb.profile.element(key)
    return e.status if e else None


def zone_keys(sb, include_optional=False):
    return {z.key for z in sb.programme if include_optional or z.priority != "optional"}


# ───────────────────────────── identity ─────────────────────────────

@pytest.mark.parametrize("text, event, family", [
    ("Luxury Sangeet for 500 people in Jaipur with a dance floor and bar", "sangeet", "wedding_celebration"),
    ("Sangeeth night for 300 guests", "sangeet", "wedding_celebration"),
    ("200-person Haldi ceremony", "haldi", "wedding_celebration"),
    ("Mehndi afternoon for 120 guests", "mehendi", "wedding_celebration"),
    ("500-person Hindu wedding mandap", "wedding_ceremony", "wedding_celebration"),
    ("1000-person music concert", "music_concert", "live_entertainment"),
    ("Minimalist technology product launch for 300 guests", "product_launch", "corporate"),
    ("A fashion show for 250 guests", "fashion_show", "fashion"),
    ("A futuristic restaurant interior for 60 covers", "restaurant", "hospitality"),
    ("An automobile exhibition for 2000 visitors", "automobile_exhibition", "exhibition"),
])
def test_event_identity_resolves_type_and_family_separately(text, event, family):
    i = read(text).profile.identity
    assert i.event_type == event
    assert i.event_family == family
    assert i.known_type


def test_family_word_does_not_override_the_event():
    """'a Sangeet for my sister's wedding' is a Sangeet, not a wedding ceremony."""
    sb = read("A Sangeet for my sister's wedding, 400 guests")
    assert sb.profile.identity.event_type == "sangeet"
    assert status(sb, "wedding_reference") == S.CONTEXTUAL      # context, not a thing to build


def test_brief_text_wins_over_a_contradicting_form_selection():
    sb = read("200-person Haldi ceremony", event_type=EventType.SANGEETH)
    assert sb.profile.identity.event_type == "haldi"
    assert any("brief was followed" in u for u in sb.intent.uncertainties)


def test_free_text_event_from_the_form_is_kept_as_its_own_identity():
    sb = read("A candlelit gathering for 80 people", event_type_text="Poetry night")
    i = sb.profile.identity
    assert (i.event_type, i.event_type_label, i.known_type) == ("poetry_night", "Poetry night", False)
    assert i.provenance == P.USER_EXPLICIT


def test_legacy_mandap_typology_alone_still_means_a_wedding_ceremony():
    sb = read("A grand celebration for 400 guests", typology=Typology.WEDDING_MANDAP)
    assert sb.profile.identity.event_type == "wedding_ceremony"


# ─────────────────────── A–J: semantic isolation ───────────────────────

def test_A_sangeet_is_performance_led_and_forbids_the_ceremony():
    sb = read("Luxury Sangeet for 500 people in Jaipur with a large dance floor, "
              "live performance stage and bar.")
    assert {"performance_stage", "dance_floor", "bar", "arrival", "circulation"} <= zone_keys(sb)
    assert "ceremony_focus" not in zone_keys(sb, include_optional=True)
    for key in HINDU_RITE | {"priest_platform", "ceremony_focus"}:
        assert status(sb, key) == S.FORBIDDEN, key
    assert sb.intent.primary_zone_key == "performance_stage"
    assert status(sb, "bar") == S.REQUIRED and sb.profile.element("bar").provenance == P.USER_EXPLICIT
    assert not sb.ritual_refs


def test_B_haldi_is_not_a_mandap():
    sb = read("200-person Haldi ceremony")
    keys = zone_keys(sb)
    assert {"haldi_seat", "wash_station"} <= keys
    assert "ceremony_focus" not in zone_keys(sb, include_optional=True)
    assert status(sb, "mandap") == S.FORBIDDEN
    assert status(sb, "ritual_fire") == S.FORBIDDEN
    assert sb.intent.primary_zone_key == "haldi_seat"
    assert "c_washable" in {i.id for i in sb.invariants}
    assert "c_sightline_all" not in {i.id for i in sb.invariants}


def test_C_hindu_wedding_carries_its_rite():
    sb = read("500-person Hindu wedding mandap")
    assert sb.profile.identity.tradition == "hindu"
    assert status(sb, "mandap") == S.REQUIRED and status(sb, "ritual_fire") == S.REQUIRED
    assert sb.zone("ceremony_focus").label == "Mandap"
    inv = {i.id: i for i in sb.invariants}
    assert inv["c_ritual_agni"].sacred
    assert "ritual:agni_kund" in sb.ritual_refs


@pytest.mark.parametrize("text, tradition, focus_label", [
    ("500-person Muslim wedding / Nikah", "muslim", "Nikah stage"),
    ("500-person Christian wedding", "christian", "Altar"),
    ("500-person Sikh wedding", "sikh", "Palki Sahib"),
])
def test_DE_other_traditions_never_receive_hindu_ritual_elements(text, tradition, focus_label):
    sb = read(text)
    assert sb.profile.identity.tradition == tradition
    for key in HINDU_RITE:
        assert status(sb, key) == S.FORBIDDEN, key
    assert sb.zone("ceremony_focus").label == focus_label
    assert "c_ritual_agni" not in {i.id for i in sb.invariants}
    assert "ritual:agni_kund" not in sb.ritual_refs


def test_tradition_is_never_guessed_from_culture():
    """'Indian' is a culture, not a rite: no Hindu fire is assumed."""
    sb = read("Create a luxury Indian wedding mandap for 500 guests.")
    assert sb.profile.identity.tradition is None
    assert status(sb, "mandap") == S.REQUIRED            # asked for by name
    assert status(sb, "ritual_fire") == S.CONTEXTUAL     # plausible, not assumed
    assert "c_ritual_agni" not in {i.id for i in sb.invariants}


@pytest.mark.parametrize("text, event", [
    ("1000-person music concert", "music_concert"),
    ("300-person corporate product launch", "product_launch"),
])
def test_FG_non_wedding_events_forbid_the_whole_wedding_vocabulary(text, event):
    sb = read(text)
    assert sb.profile.identity.event_type == event
    for key in HINDU_RITE | {"bride_and_groom", "wedding_reference", "couple_stage",
                             "ceremony_focus", "altar", "nikah_stage"}:
        assert status(sb, key) == S.FORBIDDEN, key
    # but a concert is not TOLD it has no mandap: that is not a plausible confusion
    assert not any("mandap" in c.lower() for c in sb.hard_constraints)


def test_H_fashion_runway_programme():
    sb = read("A fashion runway show for 250 guests")
    assert {"runway", "runway_seating", "backstage", "press_pit"} <= zone_keys(sb)
    assert sb.profile.audience_relationship == "surround"
    assert "model|audience" in sb.profile.relationships
    assert sb.intent.primary_zone_key == "runway"


def test_I_restaurant_works_without_being_an_event():
    sb = read("A futuristic restaurant interior for 60 covers, moderate budget.")
    assert sb.profile.identity.domain == "interior"
    assert {"dining", "service_kitchen", "entry"} <= zone_keys(sb)
    assert "c_covers" in {i.id for i in sb.invariants}
    assert sb.space_typology == "RESTAURANT"


def test_J_unknown_event_is_programmed_from_its_activities():
    sb = read("An immersive astronomy storytelling night for 350 people in Hyderabad "
              "with projection surfaces, live narration and informal seating.")
    i = sb.profile.identity
    assert not i.known_type
    assert i.event_type == "immersive_astronomy_storytelling_night"
    assert {"projection_field", "narrator_position", "informal_seating", "arrival"} <= zone_keys(sb)
    assert sb.profile.audience_relationship == "immersive"
    assert sb.intent.primary_zone_key == "projection_field"
    assert "c_projection_throw" in {i.id for i in sb.invariants}
    assert all(status(sb, k) == S.FORBIDDEN for k in ("mandap", "ritual_fire", "bride_and_groom"))


# ───────────────────────── explicit user intent ─────────────────────────

def test_explicit_request_overrides_a_default_prohibition():
    sb = read("A Sangeet for 300 guests with a small havan corner for the family")
    e = sb.profile.element("ritual_fire")
    assert e.status == S.REQUIRED and e.provenance == P.USER_EXPLICIT
    assert e.rule.startswith("user_explicit overrides")


def test_negation_excludes_an_element_and_its_zone():
    sb = read("A Sangeet for 300 guests with a dance floor, no bar please")
    assert status(sb, "bar") == S.FORBIDDEN
    assert sb.profile.element("bar").provenance == P.USER_EXPLICIT
    assert "bar" not in zone_keys(sb, include_optional=True)


def test_every_decision_carries_provenance():
    sb = read("Luxury Sangeet for 500 people with a dance floor and bar")
    assert all(z.provenance and z.rationale for z in sb.programme)
    assert all(e.provenance for e in sb.profile.elements)
    assert all(i.provenance for i in sb.invariants)
    assert sb.reasoner.source == "DETERMINISTIC"


# ───────────────────────── programme arithmetic ─────────────────────────

@pytest.mark.parametrize("text", [
    "Luxury Sangeet for 500 people with a dance floor and bar",
    "200-person Haldi ceremony", "1000-person music concert",
    "A futuristic restaurant interior for 60 covers",
    "An immersive astronomy storytelling night with projection surfaces and informal seating",
])
def test_programme_fits_the_site_and_holds_the_crowd(text):
    sb = read(text)
    built = [z for z in sb.programme if z.priority != "optional"]
    assert sum(z.area_share for z in built) <= 0.85 + 1e-6
    assert sum(z.capacity_share for z in built) >= 1.0 - 1e-6


# ─────────────────────── knowledge is data, not code ───────────────────────

def test_knowledge_base_is_referentially_consistent():
    k = load_knowledge()
    assert len(k.event_types) >= 20 and len(k.activities) >= 20
    for el in k.elements.values():
        for t in el.scope.event_types:
            assert t in k.event_types


def test_adding_an_event_type_needs_no_code(tmp_path):
    """The architecture's promise: a new event is a YAML entry."""
    src = ROOT / "v1"
    dst = tmp_path / "knowledge" / "vtest"
    shutil.copytree(src, dst)
    events = dst / "events.yaml"
    body = events.read_text(encoding="utf-8")
    marker = "event_types:\n"
    entry = """event_types:
  stargazing_retreat:
    label: Stargazing retreat
    family: cultural_programme
    aliases: [stargazing retreat]
    typology: PAVILION
    activities:
      primary: [narration, informal_seating]
    audience: immersive
    focal: "a dark sky over a field of loungers"
    elements:
      required: [narrator_position]
"""
    events.write_text(body.replace(marker, entry, 1), encoding="utf-8")
    import app.semantics.knowledge as K
    original = K.ROOT
    try:
        K.ROOT = tmp_path / "knowledge"
        k = Knowledge("vtest")
    finally:
        K.ROOT = original
    sb = DesignIntelligence(k).understand(
        DesignBrief(brief_id="bf_new", raw_text="A stargazing retreat for 60 people"), capacity=60)
    assert sb.profile.identity.event_type == "stargazing_retreat" and sb.profile.identity.known_type
    assert "narrator_position" in zone_keys(sb)
    assert status(sb, "mandap") == S.FORBIDDEN          # protected with no extra work


def test_ontology_scope_prunes_wedding_values_only_outside_their_scope(ont):
    from app.creative.program import build_program
    from app.space.instantiate import instantiate_with_relaxation

    def excluded(text):
        p = build_program(ont, DesignBrief(brief_id="bf_s", raw_text=text))
        sp = instantiate_with_relaxation(ont, p)
        return {e.value for d in sp.domains for e in d.excluded if e.rule_id == "semantic_scope"}

    concert = excluded("1000-person music concert")
    assert {"spatial_narrative:pheras", "spatial_narrative:varmala",
            "occupation_staging:varmala_platform", "occupation_staging:family_flanking"} <= concert
    assert not excluded("Create a luxury Indian wedding mandap for 500 guests.") & {
        "spatial_narrative:pheras", "spatial_narrative:varmala"}
    nikah = excluded("500-person Muslim wedding nikah")
    assert "spatial_narrative:pheras" in nikah
    assert "occupation_staging:family_flanking" not in nikah     # family-scoped, still in scope


def test_explicit_request_releases_elements_sharing_its_place():
    """'A Sangeeth mandap': the requested mandap IS the ceremony focus of the plan, so the
    generic ceremony focus cannot stay forbidden — or every concept is rejected as leaking."""
    sb = read("Create a 500-person luxury Sangeeth mandap.")
    assert sb.profile.identity.event_type == "sangeet"
    assert status(sb, "mandap") == S.REQUIRED
    assert status(sb, "ceremony_focus") == S.CONTEXTUAL
    assert sb.zone("ceremony_focus").label == "Mandap"
    assert status(sb, "ritual_fire") == S.FORBIDDEN          # not requested, still forbidden
