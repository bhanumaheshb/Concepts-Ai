# LLM Creative Synthesis + Architectural Prompt Compilation

An additive layer. The deterministic Divergence Engine is unchanged and still owns every
decision that makes the ten concepts different from each other.

## The division of labour

```
BRIEF → PROGRAMME → ANTI-BRIEF → REFERENCE / TREND → SEARCH SPACE → NICHE ALLOCATION
      → GENOTYPE / CONCEPT DNA → DIVERSITY → PORTFOLIO
                    │
                    │   ← everything above is deterministic and unchanged
                    ▼
        CREATIVE SYNTHESIS  (one concept at a time)
                    ▼
        STRUCTURED ARCHITECTURAL CONCEPT
                    ▼
              VALIDATION → REPAIR (at most once)
                    ▼
        ARCHITECTURAL PROMPT COMPILER
                    ▼
           FINAL IMAGE PROMPT → optional image generation
```

**The engine creates the possibilities; the model turns one possibility into
architecture.** The provider is handed exactly one solved Concept DNA and never sees the
other nine, so it cannot be the source of diversity even by accident — a property the
test suite asserts against the method signature itself.

## Provider independence

| Layer | Where it lives | Knows the vendor? |
|---|---|---|
| `CreativeSynthesisProvider` protocol | `app/domain/providers/protocols.py` | no |
| Prompt construction, geometry readings, constraint envelope | `app/creative/synthesis_prompt.py` | no |
| Orchestration, bounded repair | `app/creative/synthesis.py` | no |
| Validation | `app/creative/validator.py` | no |
| Prompt compilation | `app/prompt/architectural.py` | no |
| Provider logic — prompt in, structured concept out | `app/providers/llm/synthesis_provider.py` | no |
| Transport and wire dialects | `app/providers/llm/http_llm.py` | dialect only |
| **Endpoint, defaults, model list** | **`cloudflare.py`, `lmstudio.py`** | **yes** |

The provider layer is split this way because only the last files are actually
vendor-specific — each is about fifty lines, and both share one transport and one
provider class. Adding Anthropic, OpenAI or Gemini is another such file plus one line
in `composition.build_synthesis_provider`. A test walks the AST of every engine
package and fails the build if that boundary is crossed.

## Configuration

Local model via LM Studio (also llama.cpp, vLLM — only the port changes):

```
LLM_PROVIDER=lmstudio
LLM_BASE_URL=http://localhost:1234
LLM_MODEL=                    # blank => ask the server which model is loaded
LLM_TIMEOUT=300
```

Hosted via Cloudflare Workers AI:

```
LLM_PROVIDER=cloudflare
CF_ACCOUNT_ID=...             # Workers AI account id
CF_API_TOKEN=...              # token with the "Workers AI" permission
CF_MODEL=                     # blank => @cf/meta/llama-3.3-70b-instruct-fp8-fast
```

Four modes, and the difference matters:

| `LLM_PROVIDER` | Synthesis stage | Needs |
|---|---|---|
| `mock` (default) | **not run at all** — the pre-synthesis engine, byte for byte | nothing |
| `mock_synthesis` | runs, deterministic, derived from the genotype | nothing |
| `lmstudio` | runs against a local OpenAI-compatible server | a loaded model |
| `cloudflare` | runs against Cloudflare Workers AI | an API token |

The phenotype, critic and scene generators stay deterministic in every mode. Routing
them through a 4B local model would weaken the fidelity checks the critics are
calibrated against, for no gain.

### The local server names its own model

`LLM_MODEL` blank is the intended default for `lmstudio`. LM Studio ids are long and
easy to mistype (`google/gemma-3-4b`), and the server already knows which one is
loaded, so the adapter asks `/v1/models` once and reuses the answer. An explicit
`LLM_MODEL` is never overridden. The debug tab reports whichever id actually answered.

The schema is sent with `strict: true` for local models — for a 4B model that is the
difference between a grammar constraint and a polite suggestion.

### Why the native Workers AI endpoint

The Cloudflare adapter calls `/accounts/{id}/ai/run/{model}` rather than the
OpenAI-compatible route, because **Workers AI returns HTTP 200 with `success: false`**
for authentication and quota failures. Trusting the status code would surface an
expired token as an unparseable-JSON error three layers from the cause. The transport
reads the envelope instead, and an auth failure is not retried — a dead token will not
revive.

### Unconfigured is not the same as disabled

A synthesis provider with no token, or a local server that is not running, still
**enables** the stage, and each concept fails with the missing setting or the
unreachable address named. It deliberately does not fall back to `mock_synthesis`,
since that would print deterministic prose under a real model's name in the debug tab.

## What the model may and may not do

`ConstraintEnvelope` splits the world per concept:

- **HARD** — capacity, site dimensions, height, typology, every locked genotype value.
  The brief is authoritative; a concept that states a different capacity is rejected.
- **SOFT** — the programme's soft intents, open to interpretation.
- **CREATIVE** — form, sequence, module, surface, camera. Genuinely open.

Identity facets (`architectural_language`, `geometry`, `structural_logic`,
`spatial_narrative`, `emotional_register`, primary material) are locked. The model may
enrich them — "sunken" may become "a recessed ceremonial floor below the surrounding
landscape" — but may not replace them, and `DNA_NOT_EXPRESSED` fires when a locked value
appears nowhere in the output.

## Validation

One synthesis call per concept, then at most one structured repair (§20/§22). No agent
loop. For k=10 the budget is 10 calls plus only the repairs validation demands.

Checks include: required fields and minimum substance; **fields that echo their own name**
(`"seating": "Seating"` — the characteristic small-model failure, invisible to a
non-empty check); programme completeness for the actual typology; capacity and height
against the brief; locked-DNA expression; forbidden surface tokens; structural realism
with spans and supports stated; impossible architecture that is not admitted; material
behaviour rather than a shopping list; light with source, temperature, distribution and
shadow.

The impossibility check deliberately exempts the engine's own vocabulary:
`site_relationship:floating_on_water` is a pontoon, and flagging it would mean rejecting
a concept the engine deliberately chose.

## The compiler is not a pass-through

`ArchitecturalPromptCompiler` owns the 21 sections and fills each from the most
authoritative source available. `SUBJECT` always comes from the brief; a section the
model neglected is still populated from the solved genotype. Every section records its
source (`brief` / `dna` / `concept` / `reference` / `trend` / `compiler`), which is what
makes "the compiler lost the architecture" diagnosable.

With `concept=None` — no model at all — the compiler still emits all 21 sections from
DNA and brief alone, marked `degraded`. That is the §21 guarantee: ten concepts and ten
complete image prompts with no LLM key and no local model.

## Diagnosing a bad concept

`GET /api/explorations/{id}/synthesis-debug`, and the **SYNTHESIS DEBUG** tab, show the
chain per concept: Concept DNA → model input → raw structured output → validated concept
→ repairs (with the instruction sent and findings before/after) → compiled prompt with
per-section sources → prompt hash. The question "was it the engine, the model, or the
compiler?" is answered by reading down one column.
