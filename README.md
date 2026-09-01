# Creative Spatial Intelligence Engine — V1

A creative engine that takes one spatial design brief and deliberately produces **ten
conceptually divergent concepts** — with **zero image-generation API keys configured**.

The engine's terminal output is a compiled, hashed, copyable **image prompt**. Rendering
is an optional downstream adapter that the engine never imports.

```
Brief → Design Programme → Anti-Brief → Search Space → Niche Allocation
      → Genotype Solve → Phenotype Synthesis → Critics → Repair
      → Diversity → Portfolio → Scene Graph → Prompt Compilation
```

---

## Prerequisites

| Tool | Version tested |
|---|---|
| Python | 3.13 (3.11+ works) |
| Node | 24 (18+ works) |
| PostgreSQL | **not required** in V1 |

No API key of any kind is required to run this.

## Installation

```bash
# backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# frontend
cd ../frontend
npm install
```

## Environment variables

`backend/.env` (copied from `.env.example` — every default works offline):

```
MOCK_MODE=true               # master switch: no network calls of any kind
LLM_PROVIDER=mock            # mock | anthropic (adapter not implemented in V1)
EMBEDDING_PROVIDER=mock      # mock | none
IMAGE_PROVIDER=none          # none  (future: gemini | imagen | flux | openai)
ENGINE_SEED=42
ONTOLOGY_VERSION=v1
DEFAULT_K=10
MOCK_LLM_FAILURE_RATE=0.0    # >0 injects schema failures to exercise retry/repair
MOCK_CRITIC_POLICY=deterministic_only   # all_pass | deterministic_only | fail_rate:0.2
API_PORT=8000
CORS_ORIGINS=http://localhost:3000

# trend discovery (optional; the engine runs identically with it off)
TREND_PROVIDER=mock          # mock | recorded | web
SEARCH_BACKEND=none          # none | brave | tavily | serper   (web only)
SEARCH_API_KEY=              # required for TREND_PROVIDER=web
MAX_TREND_QUERIES=12
MAX_SOURCES_PER_CANDIDATE=6
SEARCH_TIMEOUT_S=8.0
SEARCH_RETRIES=2
TREND_FETCH_PAGES=false
```

### Trend providers — three states, never conflated

| `TREND_PROVIDER` | Evidence | Live? | What the UI shows |
|---|---|---|---|
| `mock` (default) | invented fixtures | no | MOCK TREND DATA |
| `recorded` | **real** URLs and publishers, replayed from a captured corpus | no | RECORDED EVIDENCE — real sources, recorded transport |
| `web` | retrieved now from a keyed search API | yes | LIVE WEB DISCOVERY |

`web` without `SEARCH_API_KEY` does **not** fall back to fixtures: discovery reports
`TREND_DISCOVERY_UNAVAILABLE` and the UI offers **Continue Without Trends**. Nothing in
the system is allowed to describe replayed or invented evidence as live.

`frontend/.env.local`:

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## Mock mode

Mock mode is the default, and it is **not a stub that returns filler**. Only the provider
calls are substituted; the deterministic engine runs for real:

- the phenotype generator builds prose **from the solved genotype** using the ontology's
  own node descriptions, so ten genotypes produce ten visibly different concepts;
- deterministic critic checks run unchanged;
- the scene solver, the distance metric, the allocator and the prompt compiler are the
  production code paths.

This means roughly 60% of the codebase — and effectively all of the IP — is developed and
benchmarked with no provider contract in existence.

## Running

```bash
# terminal 1 — backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:3000**, press **GENERATE CONCEPTS**.

## Testing

```bash
cd backend && source .venv/bin/activate
pytest -q                              # 54 tests, ~70s
pytest tests/test_pipeline.py          # divergence acceptance tests
pytest tests/test_architecture.py -q   # the image-isolation contract
```

## Example API call

```bash
curl -s -X POST http://localhost:8000/api/explorations \
  -H 'Content-Type: application/json' \
  -d '{"brief":"Create a luxury Indian wedding mandap for 500 guests.",
       "location":"Jaipur, May","project_type":"WEDDING_MANDAP","seed":42,"k":10}'
# -> {"exploration_id":"ex_...","status":"RUNNING","seed":42,"k":10}

curl -s http://localhost:8000/api/explorations/ex_... | jq '.diversity, .portfolio'
curl -s http://localhost:8000/api/concepts/cn_.../prompt | jq -r '.positive_prompt'
```

## Example briefs

1. `Create a luxury Indian wedding mandap for 500 guests.` — Jaipur, May
2. `A futuristic restaurant interior for 60 covers, moderate budget.` — Mumbai
3. `An experimental exhibition pavilion for 300 visitors.` — Berlin

Each is a button in the UI sidebar. None are hardcoded — they feed the real engine.

## Architecture overview

```
frontend (Next.js :3000) ──HTTP──▶ backend (FastAPI :8000)
                                     │
   ┌─────────────────────────────────┴───────────────────────────────┐
   │ app/api          routers (engine + a SEPARATELY mounted images) │
   │ app/creative     the 15-stage pipeline + trace                  │
   │ app/niche        curriculum · sampler · farthest-point allocator│
   │ app/genotype     constraint-respecting seeded solver            │
   │ app/diversity    distance metric · kernel · Vendi · duplicates  │
   │ app/critics      deterministic checks first, then LLM findings  │
   │ app/repair       identity-preserving targeted mutation          │
   │ app/scene        dimensioned scene graph + 4 validity checks    │
   │ app/prompt       deterministic segment compiler + hashing       │
   │ app/ontology     versioned YAML → in-memory typed graph         │
   │ app/domain       every Pydantic contract + provider protocols   │
   │ app/providers    mock LLM / embeddings / image                  │
   │ app/composition  the ONLY module that constructs providers      │
   └─────────────────────────────────────────────────────────────────┘
```

**One structural prohibition, machine-enforced:** no engine package may import a concrete
provider. `tests/test_architecture.py` walks the AST of every engine module and fails the
build if one does. This is what makes the system runnable with no image API in existence.

### Where divergence actually comes from

Not from prompting, temperature, or generating-then-filtering. The allocator picks
**ten coordinates before any concept is written**, using a distance metric over a curated
ontology, then solves a genotype inside each. Full reasoning is visible in the UI's
**CREATIVE DEBUG** tab.

Curriculum for k=10: **1 canonical · 3 adjacent · 4 exploratory · 1 radical · 1 wildcard.**

## Ontology

Source of truth is YAML in `backend/app/ontology/data/v1/`, loaded into an in-memory
typed graph at startup. **The application never writes to it.**

```
facets.yaml             16 facets (12 active, weights sum to 1.0)
nodes.yaml              203 nodes / 160 sampleable
edges.yaml              142 typed edges (excludes/requires/implies/tensions_with/inverse_of)
rules.yaml              declarative pruning + relaxation order
principles.yaml         12 cross-domain principles, pre-abstracted
cliches.yaml            curated mode seeds per typology (the anti-brief's fallback)
typology_defaults.yaml  default invariants when a brief omits them
```

To expand: add nodes/edges and bump the version. Values are **deprecated, never deleted**
(a removed value breaks every historical genotype).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Failed to fetch` in the UI | Backend not running, or `NEXT_PUBLIC_API_BASE` wrong. Check `curl localhost:8000/api/health`. |
| Exploration stays `RUNNING` | Check the uvicorn log; the pipeline runs as a background task and records `error` on the record. |
| `curriculum GAP` in the header | Not a crash — a role quota went unmet and was backfilled. The reason is in `portfolio.curriculum_gap` and the debug tab's degraded list. |
| `IMAGE NOT CONFIGURED` | Expected. No image provider is wired in V1; copy the prompt instead. |
| `OntologyError` at startup | A YAML edit broke a compile rule (unknown parent, missing `prompt_phrase`, geometry value with no scene primitive). The message names the node. |
| Concepts look similar | Open **CREATIVE DEBUG → ⑤ Niches** and check the `separation` column. If separations are high but the concepts read alike, the metric disagrees with your eye — that is the V2 metric-learning signal, not a bug. |
