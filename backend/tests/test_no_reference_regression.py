"""R-REF-15 — Reference Intelligence is ADDITIVE.

With injection=None the engine must be byte-identical to the pre-reference
implementation. Baselines were captured before any edit.

The novelty archive is an INPUT to allocation, so the replay must reproduce the
capture conditions exactly: one fresh store, the same nine runs, in the same order.
Anything else measures archive state rather than a regression.
"""
import json
import pathlib

import pytest

from app.core.hashing import sha256_of
from app.creative.pipeline import Pipeline
from app.domain.brief import DesignBrief
from app.persistence.repository import InMemoryStore

BASELINE = pathlib.Path(__file__).parent / "baselines_no_reference.json"
CAPTURE_ORDER = [
    ("mandap", "Create a luxury Indian wedding mandap for 500 guests.", "Jaipur, May"),
    ("restaurant", "A futuristic restaurant interior for 60 covers, moderate budget.", "Mumbai"),
    ("pavilion", "An experimental exhibition pavilion for 300 visitors.", "Berlin"),
]
SEEDS = (42, 7, 1234)


@pytest.fixture(scope="module")
def replay(container):
    """Replays the exact capture sequence once, against a fresh store."""
    assert BASELINE.exists(), "baseline missing — capture it before implementing"
    pipeline = Pipeline(container.ontology, container.llm, InMemoryStore(),
                        use_llm_critics=container.pipeline.use_llm_critics)
    out = {}
    for name, text, loc in CAPTURE_ORDER:
        for seed in SEEDS:
            rec = pipeline.run(
                DesignBrief(brief_id=f"bf_{name}_{seed}", raw_text=text, location=loc),
                k=10, seed=seed)
            out[f"{name}/{seed}"] = rec
    return out, json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", [n for n, _, _ in CAPTURE_ORDER])
@pytest.mark.parametrize("seed", SEEDS)
def test_genotypes_and_prompts_are_unchanged(replay, name, seed):
    runs, baseline = replay
    rec, expected = runs[f"{name}/{seed}"], baseline[f"{name}/{seed}"]

    assert sha256_of([c.genotype.model_dump(mode="json") for c in rec.concepts]) \
        == expected["genotypes"], f"{name}/{seed}: genotypes changed — NOT additive"
    assert sha256_of([rec.prompts[c.concept_id].prompt_hash for c in rec.concepts]) \
        == expected["prompts"], f"{name}/{seed}: prompt hashes changed"
    assert rec.matrix.vendi_score == expected["vendi"]
    assert rec.matrix.min_pairwise == expected["min"]
    assert [c.role.value for c in rec.concepts] == expected["roles"]


def test_no_reference_leaves_no_reference_artefacts(replay):
    runs, _ = replay
    for key, rec in runs.items():
        assert rec.injection is None, key
        assert all(c.reference_context is None for c in rec.concepts), key
        assert all(c.evaluation.originality is None for c in rec.concepts), key


def test_injection_none_is_the_only_thing_that_matters(container, ont):
    """R-REF-15, stated precisely.

    Additivity is proven by the nine baseline assertions above. This pins the remaining
    observable: on the plain path no reference object is constructed at all, so nothing
    in the reference module can influence it.
    """
    pipeline = Pipeline(ont, container.llm, InMemoryStore(),
                        use_llm_critics=container.pipeline.use_llm_critics)
    brief = DesignBrief(
        brief_id="bf_plain",
        raw_text="Create a luxury Indian wedding mandap for 500 guests.",
        location="Jaipur, May",
    )
    rec = pipeline.run(brief, k=10, seed=42)
    assert rec.injection is None
    assert rec.principle_index is not None            # always built...
    assert rec.principle_index.runtime_ids() == []    # ...and empty without a reference
    assert all(c.reference_context is None for c in rec.concepts)
