"""The Cloudflare Workers AI adapter, exercised entirely offline.

Every test here injects a transport, so the suite is identical with or without a
CF_API_TOKEN and never opens a socket. What is being pinned is the WIRE CONTRACT:
what we send, what we accept back, and — the part that motivated using Workers AI's
native endpoint — how a 200 response that is actually a failure gets reported.
"""
import json

import pytest

from app.core.config import Settings
from app.providers.llm import cloudflare
from app.providers.llm.http_llm import HttpLLM, LLMTransportError, parse_json_object

CONCEPT = {
    "concept_title": "Sunken Court of Nine Lamps",
    "concept_thesis": "A recessed ceremonial floor read from above.",
    "design_story": "The court is cut into the ground so the horizon closes.",
    "architectural_language": "corbelled masonry",
    "spatial_organization": "concentric",
    "arrival_sequence": "descent through a compressed threshold",
    "circulation": "a single ring at the upper level",
    "program": {"focal_space": "mandap", "seating": "500 guests on the upper ring",
                "walkway": "a 2.4 m ambulatory", "arrival": "from the north",
                "circulation": "ring"},
    "structure": {"structural_system": "corbelled stone", "geometry": "radial",
                  "mass_and_void": "solid rim, open centre", "module": "1.2 m",
                  "spans_and_supports": "3.6 m corbelled spans on a stone plinth"},
    "materials": {"primary": "lime-washed stone", "material_behaviour": "it chalks",
                  "surface_treatment": "bush-hammered"},
    "lighting": {"lighting_sources": ["oil lamps"], "colour_temperature": "1800K",
                 "height_and_distribution": "low, at the rim",
                 "shadow_behaviour": "long shadows across the floor"},
    "atmosphere": "held and quiet", "human_experience": "you descend and slow down",
    "camera_recommendation": {"viewpoint": "upper ring", "height": "1.6 m",
                              "lens": "35mm", "framing": "the court centred"},
    "construction_character": "dry-laid, visibly stacked",
    "rationale": "The descent is what makes the ring read as a horizon.",
}


def ok(body) -> dict:
    """A successful Workers AI envelope."""
    return {"result": {"response": body}, "success": True, "errors": [], "messages": []}


def stub(response, capture: dict | None = None):
    """A transport that records the call and returns a canned envelope."""
    def _send(method, url, payload, headers, timeout):
        if capture is not None:
            capture.update(method=method, url=url, payload=payload,
                           headers=headers, timeout=timeout)
        return response() if callable(response) else response
    return _send


def provider(response, capture=None, **kw):
    return cloudflare.build_provider(
        account_id=kw.pop("account_id", "acct_123"),
        api_token=kw.pop("api_token", "tok_secret"),
        transport=stub(response, capture), **kw)


def client(response, capture=None, **kw) -> HttpLLM:
    return cloudflare.build_client(
        account_id=kw.pop("account_id", "acct_123"),
        api_token=kw.pop("api_token", "tok_secret"),
        transport=stub(response, capture), **kw)


# ─────────────────── wire contract ───────────────────

def test_it_calls_the_native_ai_run_endpoint():
    seen: dict = {}
    client(ok(json.dumps(CONCEPT)), seen).chat_json(system="s", user="u")
    assert seen["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acct_123/ai/run/"
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    assert seen["method"] == "POST"


def test_the_token_travels_as_a_bearer_header_and_not_in_the_url():
    seen: dict = {}
    client(ok(json.dumps(CONCEPT)), seen).chat_json(system="s", user="u")
    assert seen["headers"]["Authorization"] == "Bearer tok_secret"
    assert "tok_secret" not in seen["url"]


def test_the_default_model_is_overridable():
    seen: dict = {}
    client(ok(json.dumps(CONCEPT)), seen,
           model="@cf/meta/llama-3.1-8b-instruct-fast").chat_json(system="s", user="u")
    assert seen["url"].endswith("@cf/meta/llama-3.1-8b-instruct-fast")


def test_the_schema_is_sent_as_a_json_schema_response_format():
    seen: dict = {}
    client(ok(json.dumps(CONCEPT)), seen).chat_json(
        system="s", user="u", schema={"type": "object"})
    assert seen["payload"]["response_format"] == {
        "type": "json_schema", "json_schema": {"type": "object"}}


def test_no_sampling_noise_parameter_is_sent_on_the_wire():
    """Critical rule 3, checked at the payload rather than only in the source."""
    seen: dict = {}
    client(ok(json.dumps(CONCEPT)), seen).chat_json(system="s", user="u", seed=7)
    assert seen["payload"]["seed"] == 7
    assert not {"temperature", "top_p", "top_k"} & set(seen["payload"])


# ─────────────────── the 200-that-is-a-failure ───────────────────

def test_an_auth_failure_arriving_as_http_200_is_reported_as_an_auth_failure():
    """Workers AI returns 200 with success:false for a bad token.

    Trusting the status code would surface this as 'model output was not JSON'.
    """
    body = {"result": None, "success": False,
            "errors": [{"code": 10000, "message": "Authentication error"}],
            "messages": []}
    with pytest.raises(LLMTransportError) as exc:
        client(body).chat_json(system="s", user="u")
    assert "Authentication error" in str(exc.value)
    assert "not JSON" not in str(exc.value)


def test_a_quota_failure_names_the_quota():
    body = {"result": None, "success": False,
            "errors": [{"code": 3036, "message": "Account limited: neuron quota"}]}
    with pytest.raises(LLMTransportError) as exc:
        client(body).chat_json(system="s", user="u")
    assert "neuron quota" in str(exc.value)


def test_an_auth_failure_is_not_retried():
    """A dead token will not revive; retrying only doubles the latency."""
    calls = {"n": 0}

    def counting(method, url, payload, headers, timeout):
        calls["n"] += 1
        return {"success": False,
                "errors": [{"code": 10000, "message": "Authentication error"}]}

    c = cloudflare.build_client(account_id="a", api_token="t", transport=counting)
    with pytest.raises(LLMTransportError):
        c.chat_json(system="s", user="u")
    assert calls["n"] == 1


def test_a_transient_failure_is_retried_and_can_succeed():
    attempts = {"n": 0}

    def flaky(method, url, payload, headers, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("upstream timed out")
        return ok(json.dumps(CONCEPT))

    c = cloudflare.build_client(account_id="a", api_token="t", transport=flaky)
    raw, _ = c.chat_json(system="s", user="u")
    assert attempts["n"] == 2
    assert raw["concept_title"] == CONCEPT["concept_title"]


# ─────────────────── response shapes ───────────────────

def test_a_json_object_returned_directly_is_accepted():
    """JSON mode may hand back a decoded object rather than a string."""
    raw, _ = client(ok(CONCEPT)).chat_json(system="s", user="u")
    assert raw["concept_title"] == CONCEPT["concept_title"]


def test_fenced_json_is_recovered():
    fenced = "```json\n" + json.dumps(CONCEPT) + "\n```"
    raw, _ = client(ok(fenced)).chat_json(system="s", user="u")
    assert raw["concept_title"] == CONCEPT["concept_title"]


def test_an_empty_response_is_an_error_not_an_empty_concept():
    with pytest.raises(LLMTransportError) as exc:
        client(ok("   ")).chat_json(system="s", user="u")
    assert "empty" in str(exc.value).lower()


def test_prose_with_no_json_at_all_names_what_came_back():
    with pytest.raises(LLMTransportError) as exc:
        client(ok("I cannot help with that.")).chat_json(system="s", user="u")
    assert "not JSON" in str(exc.value)


def test_parse_json_object_rejects_a_json_array():
    with pytest.raises(LLMTransportError):
        parse_json_object("[1, 2, 3]")


# ─────────────────── configuration ───────────────────

def test_missing_credentials_are_named_rather_than_guessed():
    p = cloudflare.build_provider(account_id="", api_token="")
    assert p.is_configured() is False
    assert p.missing_settings() == ["CF_ACCOUNT_ID", "CF_API_TOKEN"]


def test_an_unconfigured_provider_fails_loudly_instead_of_calling_out():
    p = cloudflare.build_provider(account_id="", api_token="tok")
    with pytest.raises(LLMTransportError) as exc:
        p.client.chat_json(system="s", user="u")
    assert "CF_ACCOUNT_ID" in str(exc.value)


def test_an_unconfigured_cloudflare_still_enables_the_synthesis_stage():
    """It must fail per concept, not silently emit deterministic prose as model output."""
    s = Settings(llm_provider="cloudflare")
    assert s.cf_api_token == ""
    assert s.synthesis_enabled is True


def test_a_blank_creative_synthesis_line_does_not_disable_synthesis(monkeypatch):
    """`.env.example` ships the key empty. Reading that as False would turn synthesis
    off for anyone who copied the file — silently, and looking like a clean run."""
    from app.core import config
    monkeypatch.setenv("LLM_PROVIDER", "cloudflare")
    monkeypatch.setenv("CREATIVE_SYNTHESIS", "")
    config.get_settings.cache_clear()
    try:
        assert config.get_settings().synthesis_enabled is True
    finally:
        config.get_settings.cache_clear()


def test_composition_builds_the_cloudflare_provider_without_credentials(container):
    from app.composition import build_synthesis_provider
    p = build_synthesis_provider(Settings(llm_provider="cloudflare"), container.ontology)
    assert p.name == "cloudflare"
    assert p.is_configured() is False


def test_a_synthesised_concept_is_stamped_with_the_provider_and_model(setup_dna):
    dna, brief, program, constraints = setup_dna
    p = provider(ok(json.dumps(CONCEPT)))
    concept = p.synthesize_concept(concept_dna=dna, brief=brief, program=program,
                                   constraints=constraints, seed=42)
    assert concept.source == "cloudflare"
    assert concept.model == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert concept.concept_title == CONCEPT["concept_title"]


@pytest.fixture(scope="module")
def setup_dna(container):
    from app.creative.program import build_program
    from app.creative.synthesis_prompt import build_constraints
    from app.domain.brief import DesignBrief
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_cf", raw_text="Create a 500-person mandap.",
                        location="Jaipur, May")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=2, seed=42)
    dna = rec.concepts[0]
    return dna, brief, program, build_constraints(ont, program, brief, dna.genotype)
