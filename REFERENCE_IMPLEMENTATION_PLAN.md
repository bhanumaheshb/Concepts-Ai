# Reference Intelligence — Implementation Plan

Approved specification is the source of truth. This document maps it onto the **actual**
repository and fixes the build order.

## 0. Regression baseline (captured before any edit)

| | |
|---|---|
| Old suite | **54 passed** |
| Baseline hashes | `backend/tests/baselines_no_reference.json` — 3 briefs × 3 seeds |
| Recorded per run | genotype-set hash, prompt-hash-set hash, vendi, min_pairwise, role order |

`test_no_reference_regression.py` asserts these exactly. If one moves, Reference
Intelligence stopped being additive and the work stops until it is understood.

## 1. Existing implementation mapping

The spec's paths are mostly right. Real symbols, verified by inspection:

| Spec name | Real location | Notes |
|---|---|---|
| `DesignBrief`, `DesignProgram` | `app/domain/brief.py` | frozen Pydantic (`Frozen` base) |
| `ConceptDNA`, `Lineage` | `app/domain/concept.py` | `principle_id: str \| None` (singular) |
| `Principle` | `app/ontology/graph.py` | **plain `@dataclass`, not frozen** → can gain defaulted fields |
| `ClicheCluster` | `app/domain/antibrief.py:16` | `evidence: Literal["CURATED","LLM","ARCHIVE"]` |
| `FacetDomain`, `ValuePrior` | `app/domain/space.py` | `ValuePrior(value, weight)` |
| `NicheRole`, `CriticName`, `ACTIVE_FACETS`, `IDENTITY_FACETS` | `app/domain/common.py` | `CriticName` has 4 members |
| `PrincipleIndex` | **does not exist** | to create |
| `Ontology` | `app/ontology/graph.py` | `.principles: dict[str, Principle]`, `.values()`, `.excludes()`, `.tensions()`, `.inverse_of()` |
| genotype solver | `app/genotype/solve.py::solve_genotype` | |
| niche allocator | `app/niche/allocator.py::allocate` | `ELIGIBLE_ROLES` lives in `app/niche/principles.py` |
| phenotype | `app/creative/phenotype.py` | `fidelity_check(..., forbidden_tokens, ...)` = **F5 already built** |
| prompt compiler | `app/prompt/compiler.py:160` | **the bug**: `if dna.principle_id in ont.principles` |
| critics | `app/critics/{codes,deterministic,runner}.py` | `evaluate()` builds `EvaluationResult` with 4 named fields |
| repair | `app/repair/engine.py` | `REPAIR_ROUTE`, `FACET_CRITICS`, `ConceptIdentity` |
| `ExplorationRecord` | `app/creative/pipeline.py` | dataclass, holds `.scenes`, `.prompts`, `.niches`, `.stage_runs` |
| provider protocols | `app/domain/providers/protocols.py` | `LLMProvider`, `EmbeddingProvider`, `ImageProvider` |
| composition | `app/composition.py` | the only place providers are constructed |
| API | `app/api/routes_engine.py`, `routes_images.py`, `serializers.py` | |
| UI | `frontend/app/page.tsx`, `components/*` | |
| architecture test | `tests/test_architecture.py` | `ENGINE_PACKAGES` list at line 10 |

### Deviations from the spec's assumed layout

1. `EvaluationResult` has **four explicitly named critic fields**, not a list. Adding
   ORIGINALITY means one new optional field `originality: CriticResult | None = None`
   plus `results()` including it when present — keeps every existing reader working.
2. `ConceptDNA.principle_id` is singular. Reference principles are carried on the new
   `reference_context`, not by widening that field.
3. `instantiate_with_relaxation` is the real entry point, not `instantiate_space`.
4. `Principle` is a mutable dataclass, so `provenance` / `role_eligibility` are plain
   defaulted fields — no migration of the YAML loader needed.

## 2. Files to MODIFY (7, all additive + defaulted)

| File | Change |
|---|---|
| `app/domain/antibrief.py` | `evidence` Literal gains `"REFERENCE"` |
| `app/domain/common.py` | `CriticName` gains `ORIGINALITY` |
| `app/domain/evaluation.py` | `EvaluationResult` gains `originality: CriticResult \| None = None` |
| `app/domain/concept.py` | `ConceptDNA` gains `reference_context: ReferenceContext \| None = None` |
| `app/ontology/graph.py` | `Principle` gains `provenance`, `role_eligibility` |
| `app/niche/principles.py` | accept a `PrincipleIndex`; honour `role_eligibility`; skip `FAR_T` for reference principles |
| `app/prompt/compiler.py` | **the lookup fix** — resolve via `PrincipleIndex` |
| `app/space/instantiate.py` | optional `prior_bias`, applied after pruning |
| `app/niche/allocator.py` | accept index + injection; dimension-diverse distribution (R-REF-20); wildcard exclusion (R-REF-03) |
| `app/critics/{codes,runner}.py` | ORIGINALITY critic wiring |
| `app/repair/engine.py` | 3 reference repair routes |
| `app/creative/pipeline.py` | `run(..., injection=None)`; wire the 5 touchpoints |
| `app/composition.py` | construct `CuratedReferenceAnalyzer` |
| `app/api/*` | 6 new endpoints + `reference` field + reference-debug |
| `tests/test_architecture.py` | `ENGINE_PACKAGES += ["references"]` |

## 3. Files to CREATE

```
app/domain/reference.py            all 18 reference domain models
app/references/__init__.py
app/references/types.py            12 types × load-bearing/secondary/absent dimensions
app/references/fixtures.py         YAML loader + the 6 authoring-rule validators
app/references/resolver.py         REF-00
app/references/analyzer.py         REF-01  (CuratedReferenceAnalyzer)
app/references/abstraction.py      REF-02  (STRIP/RELATE/LIFT/MAP/VERIFY)
app/references/synthesis.py        REF-03  (REINFORCE/BRIDGE/TENSION_HOLD/SUBSUME/DROP)
app/references/compatibility.py    ontology-edge classification
app/references/influence.py        the five bands
app/references/injection.py        REF-04  ReferenceInjectionBuilder
app/references/transformation.py   T and I, deterministic
app/references/index.py            PrincipleIndex / MergedPrincipleIndex
app/references/data/v1/*.yaml      8 fixtures + _schema.md + CHANGELOG.md
app/critics/originality.py         the fifth critic
app/api/routes_references.py       6 endpoints
frontend/components/ReferencePanel.tsx
frontend/components/ReferenceDebug.tsx
tests/test_reference_*.py          10 test files
```

## 4. Dependency order (build in this sequence)

1. **`PrincipleIndex` + compiler lookup fix + its regression test — merged alone.**
   The only change that can break the working engine.
2. Domain models (`app/domain/reference.py`) + `Principle` field extension.
3. Reference types table + fixtures + fixture validators (`test_reference_fixtures`).
4. Resolver → Analyzer (`test_reference_dna`).
5. Abstraction ladder (`test_abstraction`).
6. Influence bands (`test_influence`).
7. Injection builder — single reference (`test_surface_protection`).
8. Pipeline wiring with `injection=None` default → **run the old suite here**.
9. Transformation score + ORIGINALITY critic + gates (`test_transformation`).
10. Repair routes.
11. Compatibility + synthesis (`test_compatibility`, `test_synthesis`).
12. API endpoints.
13. UI.
14. Full benchmark (`test_reference_pipeline`).

## 5. Test order

`test_no_reference_regression` runs **first** in CI and after every step from 8 onward.
New tests are added in the same order as the modules above so a failure localises.

## 6. UI implementation order

1. `ReferencePanel` sidebar block (search → select → preset → influence).
2. Pre-Generate injection preview (DNA / principles / removed tokens) — R-REF-16.
3. Card metrics (`Influence` / `Transform`, canonical shows `— LITERAL`).
4. Drawer `REFERENCE → PRINCIPLE → CONCEPT` chain with stuck flags.
5. `REFERENCE DEBUG` fourth tab, 9 sections.

## 7. Migration / regression strategy

- Every engine change is a **defaulted optional parameter or a defaulted field**.
- `injection=None` is the default on every modified signature.
- No YAML, no schema migration, no data change to the ontology.
- `test_no_reference_regression.py` compares against the stored baseline file.
- If an existing test changes, stop and diagnose — do not update the baseline.
