"""The LM Studio adapter, exercised entirely offline.

Every test injects a transport, so the suite is identical whether or not LM Studio is
running and never opens a socket. What is pinned is the wire contract, the lazy model
resolution a local server makes possible, and the failure a stopped server produces.
"""
import json

import pytest

from app.core.config import Settings
from app.providers.llm import lmstudio
from app.providers.llm.http_llm import LLMTransportError
from tests.test_cloudflare_provider import CONCEPT


def chat(content: str | dict) -> dict:
    """A successful OpenAI-compatible chat-completions envelope."""
    text = json.dumps(content) if isinstance(content, dict) else content
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}]}


def models(*ids: str) -> dict:
    return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}


def routed(*, chat_body=None, models_body=None, capture: dict | None = None):
    """Routes GET /v1/models and POST /v1/chat/completions to canned bodies."""
    def _send(method, url, payload, headers, timeout):
        if capture is not None:
            capture.setdefault("calls", []).append(
                {"method": method, "url": url, "payload": payload,
                 "headers": headers, "timeout": timeout})
        if url.endswith("/v1/models"):
            if models_body is None:
                raise ConnectionRefusedError("connection refused")
            return models_body
        if chat_body is None:
            raise ConnectionRefusedError("connection refused")
        return chat_body() if callable(chat_body) else chat_body
    return _send


def client(**kw):
    capture = kw.pop("capture", None)
    return lmstudio.build_client(transport=routed(
        chat_body=kw.pop("chat_body", chat(CONCEPT)),
        models_body=kw.pop("models_body", models("google/gemma-3-4b")),
        capture=capture), **kw)


# ─────────────────── wire contract ───────────────────

def test_it_calls_the_openai_compatible_endpoint_on_port_1234():
    seen: dict = {}
    client(capture=seen).chat_json(system="s", user="u")
    posts = [c for c in seen["calls"] if c["method"] == "POST"]
    assert posts[0]["url"] == "http://localhost:1234/v1/chat/completions"


def test_the_base_url_is_overridable_for_llama_cpp_or_vllm():
    seen: dict = {}
    client(base_url="http://127.0.0.1:8080", capture=seen).chat_json(system="s", user="u")
    posts = [c for c in seen["calls"] if c["method"] == "POST"]
    assert posts[0]["url"] == "http://127.0.0.1:8080/v1/chat/completions"


def test_the_schema_is_sent_strict_so_the_grammar_is_enforced():
    """For a 4B model this is the difference between a constraint and a suggestion."""
    seen: dict = {}
    client(capture=seen).chat_json(system="s", user="u", schema={"type": "object"})
    posts = [c for c in seen["calls"] if c["method"] == "POST"]
    fmt = posts[0]["payload"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == {"type": "object"}


def test_no_sampling_noise_parameter_is_sent_on_the_wire():
    """Critical rule 3, checked at the payload rather than only in the source."""
    seen: dict = {}
    client(capture=seen).chat_json(system="s", user="u", seed=7)
    posts = [c for c in seen["calls"] if c["method"] == "POST"]
    assert posts[0]["payload"]["seed"] == 7
    assert not {"temperature", "top_p", "top_k"} & set(posts[0]["payload"])


# ─────────────────── lazy model resolution ───────────────────

def test_a_blank_model_is_resolved_from_the_running_server():
    """LM Studio ids are long and easy to mistype; the server already knows."""
    seen: dict = {}
    c = client(capture=seen)
    assert c.model == ""
    c.chat_json(system="s", user="u")
    posts = [x for x in seen["calls"] if x["method"] == "POST"]
    assert posts[0]["payload"]["model"] == "google/gemma-3-4b"
    assert c.model_id == "google/gemma-3-4b"


def test_an_explicit_model_is_never_overridden_by_the_server():
    seen: dict = {}
    c = client(model="my-specific-build", capture=seen)
    c.chat_json(system="s", user="u")
    posts = [x for x in seen["calls"] if x["method"] == "POST"]
    assert posts[0]["payload"]["model"] == "my-specific-build"
    assert not [x for x in seen["calls"] if x["method"] == "GET"], "should not ask"


def test_the_model_is_resolved_once_and_then_reused():
    seen: dict = {}
    c = client(capture=seen)
    c.chat_json(system="s", user="u")
    c.chat_json(system="s", user="u")
    assert len([x for x in seen["calls"] if x["method"] == "GET"]) == 1


def test_a_server_with_no_model_loaded_says_so():
    c = client(models_body=models())
    with pytest.raises(LLMTransportError) as exc:
        c.chat_json(system="s", user="u")
    assert "no chat model is loaded" in str(exc.value)


def test_an_embedding_model_is_never_chosen_for_chat():
    """LM Studio commonly serves an embedding model alongside a chat model, and it
    may be listed first. Sending a concept prompt there looks like a model fault."""
    seen: dict = {}
    c = client(models_body=models("text-embedding-nomic-embed-text-v1.5",
                                  "google/gemma-4-e4b"), capture=seen)
    c.chat_json(system="s", user="u")
    posts = [x for x in seen["calls"] if x["method"] == "POST"]
    assert posts[0]["payload"]["model"] == "google/gemma-4-e4b"


def test_only_embedding_models_loaded_is_reported_precisely():
    c = client(models_body=models("text-embedding-nomic-embed-text-v1.5"))
    with pytest.raises(LLMTransportError) as exc:
        c.chat_json(system="s", user="u")
    assert "only embedding models are loaded" in str(exc.value)


# ─────────────────── failure reporting ───────────────────

def test_a_stopped_server_names_the_address_it_tried():
    """The commonest local failure by far: LM Studio's server is simply not started."""
    c = lmstudio.build_client(transport=routed(chat_body=None, models_body=None))
    with pytest.raises(LLMTransportError) as exc:
        c.chat_json(system="s", user="u", schema={"type": "object"})
    assert "localhost:1234" in str(exc.value)


def test_truncated_output_is_named_as_truncation_not_bad_json():
    """A cut-off reply is well-formed JSON that simply stops. Reporting it as
    'not JSON' sends you to the model's competence instead of to max_tokens.

    This is not hypothetical: it is what google/gemma-4-e4b did once the schema
    started requiring spatial_sequence and anti_cliches.
    """
    cut = json.dumps(CONCEPT)[:180]
    body = {"choices": [{"message": {"content": cut}, "finish_reason": "length"}]}
    c = client(chat_body=body)
    with pytest.raises(LLMTransportError) as exc:
        c.chat_json(system="s", user="u", max_tokens=3072)
    assert "truncated" in str(exc.value)
    assert "max_tokens=3072" in str(exc.value)
    assert "LLM_MAX_OUTPUT_TOKENS" in str(exc.value)


def test_a_truncation_is_not_retried():
    """Retrying spends the same tokens to hit the same wall."""
    calls = {"n": 0}

    def counting(method, url, payload, headers, timeout):
        if url.endswith("/v1/models"):
            return models("google/gemma-4-e4b")
        calls["n"] += 1
        return {"choices": [{"message": {"content": "{\"a\": 1"},
                             "finish_reason": "length"}]}

    c = lmstudio.build_client(transport=counting)
    with pytest.raises(LLMTransportError):
        c.chat_json(system="s", user="u")
    assert calls["n"] == 1


def test_a_normal_stop_is_not_mistaken_for_truncation():
    c = client(chat_body={"choices": [{"message": {"content": json.dumps(CONCEPT)},
                                       "finish_reason": "stop"}]})
    raw, _ = c.chat_json(system="s", user="u")
    assert raw["concept_title"] == CONCEPT["concept_title"]


def test_prose_instead_of_json_is_reported_as_such():
    c = client(chat_body=chat("Sure! Here is a lovely mandap idea."))
    with pytest.raises(LLMTransportError) as exc:
        c.chat_json(system="s", user="u")
    assert "not JSON" in str(exc.value)


def test_fenced_json_from_a_chatty_model_is_recovered():
    c = client(chat_body=chat("```json\n" + json.dumps(CONCEPT) + "\n```"))
    raw, _ = c.chat_json(system="s", user="u")
    assert raw["concept_title"] == CONCEPT["concept_title"]


def test_an_unexpected_envelope_is_reported_not_swallowed():
    c = client(chat_body={"unexpected": "shape"})
    with pytest.raises(LLMTransportError) as exc:
        c.chat_json(system="s", user="u")
    assert "envelope" in str(exc.value)


# ─────────────────── configuration ───────────────────

def test_a_local_provider_is_configured_without_any_credential():
    """No key exists to check; 'configured' means we know where to look."""
    p = lmstudio.build_provider()
    assert p.is_configured() is True
    assert p.missing_settings() == []


def test_lmstudio_enables_the_synthesis_stage():
    assert Settings(llm_provider="lmstudio").synthesis_enabled is True


def test_composition_builds_the_lmstudio_provider(container):
    from app.composition import build_synthesis_provider
    p = build_synthesis_provider(Settings(llm_provider="lmstudio"), container.ontology)
    assert p.name == "lmstudio"
    assert p.client.base_url == "http://localhost:1234"
    assert p.client.strict_schema is True


def test_the_debug_tab_reports_the_model_that_actually_answered(setup_dna):
    """`model` must be a live view: a blank config resolves to the served id."""
    dna, brief, program, constraints = setup_dna
    p = lmstudio.build_provider(transport=routed(
        chat_body=chat(CONCEPT), models_body=models("google/gemma-3-4b")))
    assert p.model == ""
    concept = p.synthesize_concept(concept_dna=dna, brief=brief, program=program,
                                   constraints=constraints, seed=42)
    assert p.model == "google/gemma-3-4b"
    assert concept.source == "lmstudio"
    assert concept.model == "google/gemma-3-4b"


@pytest.fixture(scope="module")
def setup_dna(container):
    from app.creative.program import build_program
    from app.creative.synthesis_prompt import build_constraints
    from app.domain.brief import DesignBrief
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_lms", raw_text="Create a 500-person mandap.",
                        location="Jaipur, May")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=3, seed=42)
    dna = rec.concepts[0]
    return dna, brief, program, build_constraints(ont, program, brief, dna.genotype)
