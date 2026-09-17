"""The reasoning-model boundary: the adapter, and the merge that governs what a model
may contribute to Design Intelligence and the Visual Director.

No network: the HttpLLM transport is injected, and the merge tests use a fake
StructuredGenerator that returns whatever a test needs a model to say.
"""
from __future__ import annotations

import json

from app.domain.brief import DesignBrief
from app.domain.providers.protocols import StructuredGenerator, StructuredResult
from app.domain.semantics import ElementStatus as S, LLMCallRecord, Provenance as P
from app.providers.llm.http_llm import HttpLLM
from app.providers.llm.structured import HttpStructuredGenerator, flat_schema
from app.semantics.intelligence import DesignIntelligence
from app.semantics.reading import SemanticReading, ZoneProposal


# ───────────────────────────── adapter ─────────────────────────────

def _client(responses: list):
    calls = []

    def transport(method, url, payload, headers, timeout):
        calls.append(payload)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return {"choices": [{"message": {"content": json.dumps(r)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 111, "completion_tokens": 222}}

    client = HttpLLM(base_url="http://local", model="test-model", dialect="openai",
                     strict_schema=True, transport=transport, retries=0)
    return client, calls


def test_flat_schema_has_no_refs_and_is_strict():
    schema = flat_schema(SemanticReading)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    zone = schema["properties"]["zones"]["items"]
    assert zone["additionalProperties"] is False and "role" in zone["properties"]


def test_valid_answer_is_validated_and_recorded():
    client, calls = _client([{"event_type_label": "Sangeet", "primary_activities": ["dance"]}])
    gen = HttpStructuredGenerator(client, name="lmstudio")
    assert isinstance(gen, StructuredGenerator)
    res = gen.generate(stage="01", purpose="p", system="s", user="u", schema=SemanticReading)
    assert isinstance(res.value, SemanticReading) and res.value.primary_activities == ["dance"]
    r = res.record
    assert (r.success, r.attempts, r.model, r.provider) == (True, 1, "test-model", "lmstudio")
    assert (r.input_tokens, r.output_tokens) == (111, 222)
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert "temperature" not in calls[0] and "top_p" not in calls[0]


def test_malformed_answer_is_retried_with_the_validation_errors():
    client, calls = _client([{"event_type_label": ["not", "a", "string"]},
                             {"event_type_label": "Haldi"}])
    res = HttpStructuredGenerator(client, name="x").generate(
        stage="01", purpose="p", system="s", user="u", schema=SemanticReading)
    assert res.value.event_type_label == "Haldi"
    assert res.record.attempts == 2 and res.record.success
    assert "FAILED VALIDATION" in calls[1]["messages"][1]["content"]


def test_failure_is_returned_not_raised_and_not_hidden():
    from app.providers.llm.http_llm import LLMTransportError
    client, _ = _client([LLMTransportError("connection refused")])
    res = HttpStructuredGenerator(client, name="x").generate(
        stage="01", purpose="p", system="s", user="u", schema=SemanticReading)
    assert res.value is None
    assert not res.record.success and "connection refused" in res.record.error


# ───────────────────────────── merge ─────────────────────────────

class FakeReasoner:
    name = "fake"
    model = "fake-model"

    def __init__(self, reading: SemanticReading | None, error: str | None = None):
        self.reading, self.error = reading, error

    def is_configured(self):
        return True

    def generate(self, *, stage, purpose, system, user, schema, max_output_tokens=2048):
        return StructuredResult(value=self.reading, record=LLMCallRecord(
            stage=stage, purpose=purpose, schema_name=schema.__name__, model=self.model,
            provider=self.name, latency_ms=5, attempts=1, success=self.reading is not None,
            error=self.error))


def understand(text, reading, error=None):
    return DesignIntelligence(reasoner=FakeReasoner(reading, error)).understand(
        DesignBrief(brief_id="bf_m", raw_text=text), capacity=300)


def test_model_cannot_put_a_mandap_into_a_sangeet():
    sb = understand("Luxury Sangeet for 300 people with a dance floor", SemanticReading(
        event_type_label="Sangeet",
        zones=[ZoneProposal(key="mandap", label="Central mandap", role="ceremony", priority="required")],
        required_elements=["mandap", "ritual fire"],
        must_communicate=["a glowing mandap at the centre", "guests dancing"]))
    assert sb.reasoner.source == "MERGED"
    assert "mandap" not in {z.key for z in sb.programme}
    assert sb.profile.element("mandap").status == S.FORBIDDEN
    assert sb.profile.element("ritual_fire").status == S.FORBIDDEN
    assert "a glowing mandap at the centre" not in sb.intent.must_communicate
    assert "guests dancing" in sb.intent.must_communicate
    assert any("mandap" in o for o in sb.reasoner.overridden)


def test_model_cannot_override_the_users_exclusion():
    sb = understand("A Sangeet for 300 guests with a dance floor, no bar",
                    SemanticReading(event_type_label="Sangeet", required_elements=["bar counter"]))
    e = sb.profile.element("bar")
    assert e.status == S.FORBIDDEN and e.provenance == P.USER_EXPLICIT


def test_model_contributes_to_an_unknown_event_under_the_users_name():
    sb = understand(
        "An immersive astronomy storytelling night with projection surfaces and informal seating",
        SemanticReading(event_type_label="Immersive science experience",
                        event_family="installation_exhibition_cultural_programme",
                        primary_activities=["narration", "stargazing"],
                        zones=[ZoneProposal(key="telescope_terrace", label="Telescope terrace",
                                            role="participation", priority="required"),
                               ZoneProposal(key="projection_zone", label="Projection zone",
                                            role="focal")],
                        must_communicate=["faces lit by a projected night sky"]))
    i = sb.profile.identity
    assert i.event_type_label == "Immersive astronomy storytelling night"   # the user's words
    assert i.subtype == "Immersive science experience"                      # the model's, kept
    assert i.event_family == "installation"                                 # first known family
    keys = {z.key for z in sb.programme}
    assert "telescope_terrace" in keys                                      # a genuinely new zone
    assert "projection_zone" not in keys                                    # duplicate of projection_field
    tt = next(z for z in sb.programme if z.key == "telescope_terrace")
    assert tt.provenance == P.LLM_INFERENCE
    assert "faces lit by a projected night sky" in sb.intent.must_communicate


def test_model_failure_falls_back_and_says_so():
    sb = understand("200-person Haldi ceremony", None, error="timed out")
    assert sb.reasoner.source == "DETERMINISTIC" and sb.reasoner.error == "timed out"
    assert sb.profile.identity.event_type == "haldi"
    assert "haldi_seat" in {z.key for z in sb.programme}


def test_visual_director_refinement_cannot_introduce_a_forbidden_element(ont):
    from app.creative.program import build_program
    from app.space.instantiate import instantiate_with_relaxation
    from app.genotype.solve import solve_genotype
    from app.core.seeded import SeededRandom
    from app.domain.concept import ConceptDNA, Lineage
    from app.creative.phenotype import synthesise_phenotype
    from app.domain.common import NicheRole
    from app.visual.director import VisualDirector, VisualReading
    from app.composition import get_container

    brief = DesignBrief(brief_id="bf_vd", raw_text="1000-person music concert")
    program = build_program(ont, brief)
    space = instantiate_with_relaxation(ont, program)
    g = solve_genotype(ont, space, SeededRandom(1, "t"))
    ph, _, _ = synthesise_phenotype(get_container().llm, ont, program, g,
                                    role=NicheRole.CANONICAL, seed=1)
    from app.core.versions import VersionStamp
    dna = ConceptDNA(concept_id="cn_vd", exploration_id="ex_vd", niche_id="n", niche_index=0,
                     role=NicheRole.CANONICAL, lineage=Lineage(origin="ALLOCATED"), genotype=g,
                     phenotype=ph, versions=VersionStamp(ontology_version=ont.version), status="DRAFT")

    class Director(FakeReasoner):
        def generate(self, **kw):
            res = super().generate(**kw)
            return res.model_copy(update={"value": VisualReading(
                story_of_image="a bride and groom under a mandap as the band plays",
                composition="crowd in the foreground, lit stage beyond",
                human_activity="thousands with hands raised toward the stage")})

    intents = VisualDirector(ont, reasoner=Director(None)).direct(dna=dna, program=program)
    hero = next(i for i in intents if i.view_key == "hero")
    assert "mandap" not in hero.story_of_image and "bride" not in hero.story_of_image
    assert hero.composition == "crowd in the foreground, lit stage beyond"
    assert hero.provenance["composition"] == "llm"
    assert any("story_of_image rejected" in o for o in hero.overridden)
