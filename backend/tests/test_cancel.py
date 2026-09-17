"""Stopping a run: at a stage boundary or between concepts, keeping what exists."""
from __future__ import annotations

import threading

from app.creative.pipeline import Pipeline
from app.creative.synthesis import CreativeSynthesizer
from app.domain.brief import DesignBrief
from app.persistence.repository import InMemoryStore
from app.providers.llm.mock_synthesis import MockCreativeProvider

BRIEF = "Luxury Sangeet for 300 people with a dance floor and bar"


def _pipeline(container, synth=None):
    return Pipeline(container.ontology, container.llm, InMemoryStore(), use_llm_critics=False,
                    synthesizer=synth)


def test_a_cancelled_run_stops_before_doing_any_work(container):
    flag = threading.Event()
    flag.set()
    rec = _pipeline(container).run(DesignBrief(brief_id="bf_c0", raw_text=BRIEF),
                                   k=3, seed=42, cancel=flag)
    assert rec.status == "CANCELLED"
    assert rec.stage_runs == [] and rec.concepts == []
    assert rec.error is None


def test_cancelling_during_synthesis_keeps_the_concepts_already_written(container):
    flag = threading.Event()

    class StopAfterFirst(MockCreativeProvider):
        def synthesize_concept(self, **kw):
            out = super().synthesize_concept(**kw)
            flag.set()                       # the user presses Stop while concept 1 is written
            return out

    ont = container.ontology
    rec = _pipeline(container, CreativeSynthesizer(ont, StopAfterFirst(ont))).run(
        DesignBrief(brief_id="bf_c1", raw_text=BRIEF), k=3, seed=42, cancel=flag)
    assert rec.status == "CANCELLED"
    assert len(rec.concepts) == 3                 # the portfolio was already selected
    assert len(rec.structured) == 1               # only the concept in flight was written
    assert "14c" not in {s.stage for s in rec.stage_runs}


def test_cancelled_concepts_are_settled_for_the_ui(container):
    from app.api.serializers import concept_summary
    flag = threading.Event()

    class StopAfterFirst(MockCreativeProvider):
        def synthesize_concept(self, **kw):
            out = super().synthesize_concept(**kw)
            flag.set()
            return out

    ont = container.ontology
    rec = _pipeline(container, CreativeSynthesizer(ont, StopAfterFirst(ont))).run(
        DesignBrief(brief_id="bf_c2", raw_text=BRIEF), k=3, seed=42, cancel=flag)
    cards = [concept_summary(ont, rec, c)["synthesis"] for c in rec.concepts]
    assert all(card is not None for card in cards)                 # nothing left spinning
    assert sum(1 for card in cards if card.get("stopped")) == 2


def test_cancel_endpoint_for_an_unknown_run_is_404():
    from fastapi.testclient import TestClient
    from app.main import create_app
    r = TestClient(create_app()).post("/api/explorations/ex_does_not_exist/cancel")
    assert r.status_code == 404
