# Creative Spatial Intelligence Engine — V1 Implementation Plan

## 1. Current repository state

Repository was **empty** at the start of implementation (`git init` performed here).

Toolchain verified on this machine:

| Tool | Version | Note |
|---|---|---|
| Python | 3.13.7 | backend |
| Node | 24.9.0 | frontend |
| npm | 11.6.0 | frontend |
| git | 2.53.0 | |
| psql | **not installed** | Postgres deferred — see §5 |

## 2. Architecture

Two processes, one hard architectural rule.

```
frontend (Next.js :3000)  ──HTTP──▶  backend (FastAPI :8000)
                                        │
                                        ├── creative engine  (deterministic core + LLM stages)
                                        ├── ontology         (versioned YAML → in-memory graph)
                                        └── providers        (LLM / Embedding / Image — all mockable)
```

**Rule:** no engine package may import a concrete provider. Providers are reached only
through `app.domain.providers.protocols` and are constructed in `app/composition.py`.
This is what allows the whole system to run with `MOCK_MODE=true` and no API keys,
and it is enforced by a test (`tests/test_architecture.py`).

### Layering (imports point downward only)

```
api / creative
    ↓
critics · repair · scene · prompt · mutation · niche · genotype · space · diversity
    ↓
ontology
    ↓
domain            (pure schemas + protocols; imports nothing internal)
```

## 3. Modules to create

### Backend

| Module | Responsibility |
|---|---|
| `app/core/` | config, seeded RNG, canonical hashing, version stamps, ids |
| `app/domain/` | every Pydantic contract (brief, program, genotype, phenotype, concept, evaluation, diversity, portfolio, scene, prompt, trace) + provider protocols |
| `app/ontology/` | versioned YAML data, loader, graph (LCA/depth/edges), rule engine, principle library |
| `app/space/` | search-space instantiation: prune facet domains from program + rules |
| `app/niche/` | curriculum, candidate sampler, farthest-point allocator |
| `app/genotype/` | genotype completion (constraint-respecting seeded solve) |
| `app/diversity/` | per-type distance functions, weighted aggregate, matrix, Vendi, duplicate gate |
| `app/critics/` | finding codes, deterministic checks, LLM critics, runner, score derivation |
| `app/repair/` | identity extraction, finding→operator routes, repair executor |
| `app/mutation/` | typed genotype operators + registry + pinning |
| `app/scene/` | scene-graph build, dimension solver, four validity checks |
| `app/prompt/` | deterministic segment compiler, hashing, negative-prompt assembly |
| `app/providers/` | mock LLM / embedding / image implementations |
| `app/creative/` | the staged pipeline runner + trace assembly |
| `app/persistence/` | repository protocol + in-memory implementation |
| `app/api/` | engine routes, image routes (separately mounted), health/config |

### Frontend

| Page | Purpose |
|---|---|
| `/` | brief form → live stage progress → 10 concept cards |
| `/exploration/[id]` | portfolio view + comparison table + debug panel |
| `/exploration/[id]/concept/[cid]` | full concept: DNA table, rationale, scene graph, **final prompt + copy** |

## 4. Implementation order

1. `core` + `domain` schemas
2. Ontology data (v1 YAML) + loader + graph
3. Diversity metric (pure, testable with zero dependencies)
4. Space instantiation → niche allocation → genotype solve  ← *the divergence proof*
5. Provider protocols + mock providers
6. Anti-brief + principles
7. Phenotype synthesis (mock generates from genotype, not from thin air)
8. Critics → repair
9. Portfolio selection → scene graph → prompt compiler
10. Pipeline runner + trace
11. API
12. Frontend
13. Tests + run

## 5. Dependencies

**Backend:** `fastapi`, `uvicorn`, `pydantic>=2`, `pyyaml`, `pytest`, `httpx`.
No `numpy` requirement for the core metric (Vendi uses a small pure-Python
symmetric eigensolver) so the engine has no heavy native dependency.

**Frontend:** `next`, `react`, `typescript`. No UI framework, no state library.

**PostgreSQL is deliberately not used in V1.** The first vertical slice needs no
persistence beyond process lifetime. `app/persistence/repository.py` defines the
protocol; `memory.py` implements it. Adding Postgres later means one new
implementation and one line in `composition.py` — no engine change.

## 6. Environment variables

```
MOCK_MODE=true            # master switch; true ⇒ no network calls of any kind
LLM_PROVIDER=mock         # mock | anthropic
EMBEDDING_PROVIDER=mock   # mock | none
IMAGE_PROVIDER=none       # none | (future: gemini | flux | imagen)
ENGINE_SEED=42            # default seed when a request omits one
ONTOLOGY_VERSION=v1
API_PORT=8000
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

No API key is required for any of these values.

## 7. Development commands

```
# backend
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev

# tests
cd backend && pytest -q
```

## 8. Testing strategy

- **Unit**: distance-metric properties, ontology load/compile, CSP legality,
  allocator determinism + min-distance invariant, prompt-compiler byte stability.
- **Integration**: full pipeline in mock mode, no network.
- **Divergence**: the same brief across 3 seeds must stay aligned, stay distinct,
  keep a valid curriculum, and be reproducible per seed.
- **Architecture**: an automated import check that no engine module reaches a
  concrete provider.

## 9. First vertical slice

`POST /api/explorations` with a one-sentence brief returns a `Portfolio` of 10
concepts, each carrying genotype, phenotype, scores, niche role, scene graph and a
compiled image prompt — produced with `MOCK_MODE=true`, no network, no API keys.
The UI renders the pipeline stages, the ten cards, the comparison table, the debug
panel, and a copyable final prompt.
