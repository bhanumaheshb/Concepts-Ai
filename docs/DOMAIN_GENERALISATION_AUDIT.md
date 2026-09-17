# Domain generalisation — engineering audit

Baseline commit: `7626ea7`. Written before any change to the engine.

## 1. Current flow

```
BriefForm (UI)                      project_type=WEDDING_MANDAP, event_type=SANGEETH  ← DEFAULTS
  → POST /api/explorations          closed enums; unknown event strings → GENERIC_EVENT
  → DesignBrief                     typology + event_type + tradition + venue_type
  → 01 brief parsing                no-op (detail string only)
  → 02 build_program                typology keyword match → typology_defaults.yaml
                                      → required_zones, invariants, ritual profile
                                    + mock ProgramProposal (keyword soft intents)
  → 04 instantiate_space            12 ACTIVE_FACETS × ontology values, pruned by rules
                                      (budget/climate/site) and typ_low affinity
  → 03 antibrief                    cliches.yaml[typology]
  → 05–07 allocate                  niches CANONICAL→WILDCARD, genotype solve, principles
  → 08 phenotype                    deterministic prose from genotype
  → 08c cognition                   REINTERPRET/INVERT/… over antibrief assumptions
  → 13 scene graph                  zones = program.required_zones; focal = first sacred invariant
  → 09 critics                      ALIGNMENT / COHERENCE / FEASIBILITY / CULTURAL
  → 09c evolution, 10 repair, 11 diversity, 12 portfolio
  → 14 compile_prompt               deterministic segments
  → 14b synthesis (LM Studio)       ConstraintEnvelope: "The concept is a <typology>"
                                    ArchitecturalPromptCompiler: SUBJECT "A <typology> for N"
                                    ViewPromptCompiler: EVENT_CATALOGUE[event] / VIEW_CATALOGUE[typology]
```

The only real LLM in the deterministic stages is **none**: `llm` is always the mock
provider. The configured model (LM Studio) is reached only at 14b. Nothing in the
pipeline *understands* the brief before the creative search starts.

## 2. Root causes

| # | Root cause | Effect |
|---|---|---|
| R1 | **`Typology.WEDDING_MANDAP` carries event semantics.** It is a space form *and* a ceremony: its defaults inject a `ceremony` zone, a "sightline to the ceremonial centre" invariant and `ritual:seating_sightline`. | Any brief resolved to this typology — a Sangeet, a Haldi, a reception — is programmed as a mandap ceremony. |
| R2 | **The UI defaults every brief to `WEDDING_MANDAP` + `SANGEETH`.** | A concert, a product launch or a Haldi typed into the box arrives as a Sangeet-in-a-mandap, marked as an explicit user choice. |
| R3 | **Event identity is a closed 7-value enum.** Unknown strings silently become `GENERIC_EVENT`. | A fashion show, concert, or "astronomy storytelling night" loses its identity at the API boundary. There is no representation for family vs type. |
| R4 | **Keyword typology classification.** `"wedding"` anywhere → mandap; `"reception"` → INTERIOR; `"bar "` → RESTAURANT; `"stage"` → EVENT_STAGE. | "Sangeet with a live band stage" → EVENT_STAGE; "wedding reception" → mandap; "hotel reception lobby" and "wedding reception" collide. |
| R5 | **Wedding-only values live in the universal search space.** `spatial_narrative:{welcome,varmala,pheras,vidaai}`, `occupation_staging:{baraat_arrival,varmala_platform,family_flanking,floor_seated}` are legal for every brief. | A restaurant or concert genotype can be solved with a *pheras* narrative or a *varmala platform*. The genotype itself leaks, not just the prose. |
| R6 | **No negative semantics anywhere.** The system has anti-*clichés* (aesthetic) but no notion of *forbidden elements* (semantic). | Nothing can say "a Sangeet must not contain a ritual fire", so nothing checks it. |
| R7 | **Programme = typology lookup table**, not inference from activities. | A new event needs a new typology + YAML block + view catalogue entry + UI enum + API enum. |
| R8 | **Ceremony vocabulary hard-coded in downstream fallbacks.** Scene `PRIMARY_ROLES` starts with `ceremony`; architectural compiler writes "a processional route to the focal space" for every concept; views' `_PATHWAY` camera is "along the processional axis"; mock cognition reinterprets "the ceremonial focus"; synthesis rule 7 cites a mandap as its example. | Even a correctly programmed non-wedding brief is *described* as a ceremony when the model is silent. |
| R9 | **Critics cannot see semantics.** CULTURAL checks abstraction floors only. No critic checks programme coverage against the *event*, and none detects cross-domain leakage. | Leakage is never rejected, only occasionally avoided. |
| R10 | **Prompt SUBJECT is the typology label** ("A wedding mandap for 300 people") and the view list is keyed by a closed event enum. | The image prompt for a Sangeet literally says "wedding mandap" — seen in the earlier run logs. |

## 3. Wedding-coupled files (direct)

`domain/common.py` (Typology, EventType, Tradition) · `domain/brief.py` (RitualProfile,
`sacred_refs`, RITUAL category) · `creative/program.py` (TYPOLOGY_KEYWORDS, tradition
blocks) · `ontology/data/v1/typology_defaults.yaml` · `ontology/data/v1/nodes.yaml`
(wedding narrative/staging values) · `ontology/data/v1/cliches.yaml` · `prompt/views.py`
(FOCAL_BY_TRADITION, EVENT_CATALOGUE, VIEW_CATALOGUE.WEDDING_MANDAP) ·
`prompt/architectural.py` (processional fallback, style) · `scene/build.py`
(PRIMARY_ROLES) · `creative/validator.py` (GATHERING_TYPOLOGIES) ·
`creative/synthesis_prompt.py` · `providers/llm/mock_synthesis.py` ·
`providers/llm/mock_cognition.py` · `api/routes_engine.py` · `frontend/components/BriefForm.tsx`
· `frontend/lib/api.ts`.

## 4. Indirect assumptions

- `DesignProgram.sacred_refs()` / `Constraint.sacred` — correct *mechanism* (immutable
  constraints), wedding-shaped *naming*. Keep the mechanism; it is how any hard
  semantic requirement stays out of reach of mutation.
- Scene `focal_point` is linked to "the first sacred invariant" — assumes one ritual focus.
- Scene `sightline` edge from guests to focal — assumes a single frontal focus; wrong
  for exhibitions, restaurants, festivals.
- Anti-brief `qa_sacred` "the ritual elements could be omitted" — only meaningful for rites.
- Novelty archive keyed by `typology` — a Sangeet is compared against past mandaps.
- `ProgramResolution.focal_space / seating / walkway` — assumes every programme has one
  focus, seating and a walkway.
- Synthesis `build_user_prompt` prints `z.name` on `RequiredZone`, which has no `name`,
  so the model receives `zone='ceremony' min_area_m2=60.0 capacity=0` repr strings.

## 5. Schemas that need generalisation

| Schema | Change |
|---|---|
| — (new) | `EventProfile`, `DesignIntent`, `ProgramZone`, `SemanticElement`, `Provenance`, `SemanticBrief` |
| `DesignBrief` | `event_type_text: str` — free text identity preserved alongside the legacy enum |
| `DesignProgram` | `semantic: SemanticBrief \| None`; zones and invariants sourced from it |
| `Constraint.source` | + `SEMANTIC` |
| ontology `Node` | `scope` — which semantic contexts a value belongs to |
| `EvaluationResult` | + `semantic` critic result, included in the gate |
| — (new) | `VisualIntent` (visual director output), `LLMCallRecord` |

## 6. Pipeline stages affected

01 (becomes Design Intelligence), 02 (programme inference), 03 (cliché lookup by
profile), 04 (scope pruning + semantic priors), 08c (primitives), 13 (primary role,
focal), 09 (semantic + leakage critic), 14/14b (subject, envelope, validator),
new 14c Visual Director, views.

## 7. Target architecture

```
brief ─► DesignIntelligence ──────────────────────────────► SemanticBrief
          ├ lexical grounding (deterministic): aliases, explicit element requests,
          │   activities, capacity, location, UI selections        [USER_EXPLICIT / DETERMINISTIC_RULE]
          ├ ReasoningModel (structured, validated, retried)       [LLM_INFERENCE]
          └ merge under invariants: knowledge base + scope rules  [DOMAIN_KNOWLEDGE]
               user-explicit > scope-forbidden > knowledge > LLM
      ─► programme inference: event zones ∪ activity-implied zones ∪ requested elements
                               ∪ universal (arrival, circulation) ∪ scale-implied service
      ─► DesignProgram(semantic=…)  → search space prunes out-of-scope values,
                                      biases staging by audience relationship
      ─► unchanged creative search (niches / genotype / cognition / critics / repair / diversity)
            + SEMANTIC critic (coverage + leakage, deterministic)
      ─► Visual Director → VisualIntent (deterministic, optional LLM refinement)
      ─► prompt compiler consumes VisualIntent; leakage-checked; forbidden → negatives
```

Knowledge lives in data (`app/semantics/knowledge/*.yaml`): families, event types,
activities → zones, elements → scope. **Adding an event type is a YAML entry; an event
not in the YAML is inferred from its activities.**

Why not a dynamic genotype: the twelve active facets are already universal
(thesis, language, geometry, structure, material, narrative, staging, light, site,
tectonic, scale, register). The coupling is in the *values*, so the fix is value
scoping — domain extensions at the value level — not a variable-width genotype that
would invalidate the distance metric, the allocator and every stored archive.

## 8. Migration strategy

1. Additive schemas; legacy enums kept as *hints*, never as the identity.
2. `DesignIntelligence` always runs; with no reasoning model it is deterministic and
   says so in the trace (`reasoner.source=DETERMINISTIC`).
3. Typology stops carrying event semantics: zones/ritual invariants come from the profile.
4. Scope annotations on existing ontology values; no value removed.
5. UI defaults → "detect from brief".
6. Baselines in `baselines_no_reference.json` **will change** for any brief where the
   old search space was leaking. They are re-captured deliberately and the reason is
   recorded; the reference-additivity property those tests guard is re-verified on the
   new baseline.

## 9. Test strategy

- Unit: profile resolution, element scoping, programme inference, unknown events,
  reasoner merge precedence, structured generator retry/validation.
- Semantic isolation (A–J): full pipeline runs; assertions on *structured* state —
  `profile.event_type`, programme zone keys, forbidden set, genotype refs, scene zone
  roles, critic findings, visual intent, final prompt text — never on exact prose.
- Invariants: forbidden element in scene/prompt ⇒ SEMANTIC critic BLOCKER; explicit
  request overrides default prohibition.
- Regression: full existing suite.

## 10. Risk areas

- Baseline churn masking a real regression → re-capture only after the isolation
  suite passes and the diff is explained.
- Lexical leakage detection false positives ("stage" in "staged", "altar" in
  "altarpiece") → word-boundary matching, multi-word aliases, per-element aliases.
- 4B local model producing malformed semantic JSON → schema validation, one repair
  retry, deterministic fallback recorded as degraded.
- LM Studio latency (~3 min per synthesis call) → semantic reasoning is ONE call per
  run; visual reasoning is deterministic by default with LLM refinement opt-in.
- Tradition inference → never inferred from a single element; a Hindu rite requires
  the tradition to be stated or selected.
