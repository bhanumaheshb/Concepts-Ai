import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _complete(client, payload):
    r = client.post("/api/explorations", json=payload)
    assert r.status_code == 202
    eid = r.json()["exploration_id"]
    for _ in range(80):
        g = client.get(f"/api/explorations/{eid}")
        if g.status_code == 200 and g.json()["status"] in ("COMPLETE", "FAILED"):
            return eid, g.json()
        time.sleep(0.05)
    raise AssertionError("exploration did not complete")


def test_health_and_config(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["ontology"]["active_facets"] == 12
    cfg = client.get("/api/config").json()
    assert cfg["image_generation_required"] is False
    assert cfg["providers"]["image"]["configured"] is False


def test_full_exploration_flow(client):
    eid, data = _complete(client, {"brief": "Create a luxury Indian wedding mandap for 500 guests.",
                                   "location": "Jaipur, May", "seed": 42})
    assert data["status"] == "COMPLETE"
    assert len(data["concepts"]) == 10
    assert data["diversity"]["vendi_score"] >= 6.5
    assert data["portfolio"]["curriculum_satisfied"] is True
    assert len(data["stages"]) == 15

    cid = data["concepts"][0]["concept_id"]
    detail = client.get(f"/api/concepts/{cid}").json()
    assert detail["design_thesis"] and detail["concept_dna"] and detail["rationale_chain"]
    assert detail["scene_graph"]["status"] in ("COMPLETE", "PARTIAL")
    assert len(detail["distances"]) == 9

    prompt = client.get(f"/api/concepts/{cid}/prompt").json()
    assert prompt["positive_prompt"] and prompt["negative_prompt"]
    assert prompt["prompt_hash"] and prompt["compiler_version"]

    rows = client.get(f"/api/explorations/{eid}/comparison").json()["rows"]
    assert len(rows) == 10
    assert len({r["architecture"] for r in rows}) >= 7

    dbg = client.get(f"/api/explorations/{eid}/debug").json()
    for key in ("design_program", "anti_brief", "search_space", "niches",
                "genotypes", "critics", "diversity_matrix", "prompts"):
        assert dbg[key], f"debug payload missing {key}"


def test_image_generation_is_not_configured_but_never_errors(client):
    eid, data = _complete(client, {"brief": "An experimental exhibition pavilion for 300 visitors.",
                                   "seed": 7})
    cid = data["concepts"][0]["concept_id"]
    prompt = client.get(f"/api/concepts/{cid}/prompt").json()
    r = client.post("/api/images/generate", json={"prompt_id": prompt["prompt_id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "NOT_CONFIGURED"
    assert body["prompt_echo"] == prompt["positive_prompt"]   # copyable regardless


def test_mutate_and_combine(client):
    eid, data = _complete(client, {"brief": "A futuristic restaurant interior for 60 covers.",
                                   "seed": 1234})
    a, b = data["concepts"][0]["concept_id"], data["concepts"][5]["concept_id"]

    m = client.post(f"/api/concepts/{a}/mutate", json={"intent": "unexpected"})
    assert m.status_code == 200, m.text
    assert m.json()["distance_from_parent"] > 0.0
    assert m.json()["concept"]["lineage"]["origin"] == "MUTATED"

    p = client.post(f"/api/concepts/{a}/mutate", json={"intent": "practical"})
    assert p.status_code == 200

    comb = client.post(f"/api/concepts/{a}/combine", json={"other_id": b})
    assert comb.status_code == 200, comb.text
    assert comb.json()["concept"]["lineage"]["origin"] == "HYBRIDISED"
    assert len(comb.json()["concept"]["prompt"]["positive_prompt"]) > 50


def test_rate_attributes_feedback_to_facets(client):
    eid, data = _complete(client, {"brief": "A quiet memorial pavilion for 50 people.", "seed": 3})
    cid = data["concepts"][0]["concept_id"]
    r = client.post(f"/api/concepts/{cid}/rate", json={"kind": "boring", "reason_code": "too_expected"})
    assert r.json()["ok"] and r.json()["facets_attributed"] > 5
