"""Re-capture tests/baselines_no_reference.json.

Run ONLY when an intentional change moves the no-reference output, and say why in
the commit. The replay here must match `test_no_reference_regression.replay` exactly:
one fresh store, the same nine runs, in the same order, with the same pipeline.

    python -m tests.capture_no_reference_baseline

History:
  PRE_ONTOLOGY_v1_376dba44 — before the ontology expansion.
  PRE_SEMANTICS            — before Design Intelligence. The old search space let
                             wedding-only values (pheras, varmala platform, family
                             flanking) into restaurant and pavilion genotypes, and the
                             programme came from typology tables. Both were the defect
                             being fixed, so these baselines had to move.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile

os.environ["LLM_PROVIDER"] = "mock"
os.environ["SESSIONS_DIR"] = tempfile.mkdtemp(prefix="concepts-capture-")
os.environ["SEMANTIC_REASONER_ENABLED"] = "false"
os.environ["VISUAL_REASONER_ENABLED"] = "false"

from app.composition import get_container  # noqa: E402
from app.core.hashing import sha256_of  # noqa: E402
from app.creative.pipeline import Pipeline  # noqa: E402
from app.domain.brief import DesignBrief  # noqa: E402
from app.persistence.repository import InMemoryStore  # noqa: E402
from tests.test_no_reference_regression import BASELINE, CAPTURE_ORDER, SEEDS  # noqa: E402


def main(archive_as: str | None = "PRE_SEMANTICS") -> None:
    container = get_container()
    pipeline = Pipeline(container.ontology, container.llm, InMemoryStore(),
                        use_llm_critics=container.pipeline.use_llm_critics)
    out = {}
    for name, text, loc in CAPTURE_ORDER:
        for seed in SEEDS:
            rec = pipeline.run(
                DesignBrief(brief_id=f"bf_{name}_{seed}", raw_text=text, location=loc),
                k=10, seed=seed)
            assert rec.status == "COMPLETE", rec.error
            out[f"{name}/{seed}"] = {
                "genotypes": sha256_of([c.genotype.model_dump(mode="json") for c in rec.concepts]),
                "prompts": sha256_of([rec.prompts[c.concept_id].prompt_hash for c in rec.concepts]),
                "vendi": rec.matrix.vendi_score,
                "min": rec.matrix.min_pairwise,
                "roles": [c.role.value for c in rec.concepts],
            }
            print(f"{name}/{seed}: {len(rec.concepts)} concepts vendi={rec.matrix.vendi_score}")
    target = pathlib.Path(BASELINE)
    if archive_as and target.exists():
        keep = target.with_name(f"baselines_no_reference.{archive_as}.json")
        if not keep.exists():
            shutil.copy(target, keep)
    target.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
