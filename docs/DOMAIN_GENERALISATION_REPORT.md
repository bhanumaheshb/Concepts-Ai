# Domain generalisation — engineering report

Companion to [DOMAIN_GENERALISATION_AUDIT.md](DOMAIN_GENERALISATION_AUDIT.md), which was
written before any change. Commits `7626ea7` (checkpoint) → `b67e1cd` → `fae9cd8` →
`e88cd08` → `86721e7` → the final commit of this work.

## 1. Root cause

The engine had no representation of *what was being designed*. Event meaning was
smuggled through a space-form enum:

- `Typology.WEDDING_MANDAP` was simultaneously a space form **and** a ceremony: its
  defaults injected a `ceremony` zone, a "sightline to the ceremonial centre" invariant
  and a ritual profile into any brief that resolved to it.
- The UI defaulted every brief to `WEDDING_MANDAP` + `SANGEETH` and sent those as
  explicit choices — so a concert, a Haldi or a product launch arrived as a Sangeet in
  a mandap.
- Event identity was a closed 7-value enum; anything else became `GENERIC_EVENT`.
- Wedding-only ontology values (`pheras`, `varmala`, `varmala_platform`,
  `family_flanking`, `baraat_arrival`) were legal in every search space.
- There were no negative semantics, no critic that could see semantics, and prompt
  SUBJECT / shot lists were keyed by typology and a closed event catalogue.

## 2. Architecture before

```
brief ─► typology keyword match ─► typology_defaults.yaml (zones, invariants, rites)
      ─► search space (12 facets, all values legal) ─► niches / genotypes / cognition
      ─► scene (primary role "ceremony" first) ─► 4 critics ─► portfolio
      ─► synthesis ("The concept is a <typology>") ─► compiler (SUBJECT = typology,
         shots = EVENT_CATALOGUE[enum] or VIEW_CATALOGUE[typology])
```

## 3. Architecture after

```
brief + form
  ─► 01 DESIGN INTELLIGENCE ──────────────────────────────► SemanticBrief
        grounding (deterministic): event / tradition / activities / elements named or
          excluded in the brief, resolved against the knowledge base
        reasoning (optional model, StructuredGenerator): a validated SemanticReading
        merge: user explicit > scope rules > domain knowledge > model inference
        programme inference: activity zones ∪ event zones ∪ element zones ∪ universals
  ─► 02 programme  (typology = physical defaults only; zones/invariants/rites from semantics)
  ─► 04 search space  (out-of-scope values pruned with recorded exclusions;
                        semantic priors carried on the space)
  ─► 03 anti-brief   (clichés: event > family > typology; assumptions from the
                       event's own relationships)
  ─► 05–07 allocation (semantic priors applied by role: canonical 1.0 … radical 0)
  ─► 08 / 08c cognition (operators act on the event's design primitives)
  ─► 13 scene (focus = the semantic primary zone) ─► 09 critics + SEMANTIC critic
  ─► 09c / 10 / 11 / 12 unchanged
  ─► 14b synthesis (told what the event is, what it must not contain; leak = ERROR)
  ─► 14c VISUAL DIRECTOR ─► VisualIntent per view ─► compilers (leak-stripped)
```

## 4. Files changed

Engine: `domain/{brief,common,evaluation,space,synthesis,providers/protocols}.py`,
`creative/{pipeline,program,antibrief,validator,synthesis_prompt,mockgen}.py`,
`space/instantiate.py`, `genotype/solve.py`, `niche/allocator.py`, `scene/build.py`,
`critics/{codes,deterministic,runner}.py`, `repair/engine.py`,
`creative_cognition/{operators,engine}.py`, `prompt/{architectural,views,compiler}.py`,
`trends/domains.py`, `ontology/graph.py`, `ontology/data/v1/{nodes,cliches,typology_defaults}.yaml`.
Providers/composition: `providers/llm/{http_llm,mock_synthesis,mock_cognition}.py`,
`composition.py`, `core/config.py`, `persistence/sessions.py`.
API: `api/{routes_engine,serializers}.py`. Frontend: `components/BriefForm.tsx`,
`app/page.tsx`, `lib/api.ts`, `app/globals.css`.

## 5. New schemas, classes, modules

| Module | Contents |
|---|---|
| `domain/semantics.py` | `Provenance`, `ElementStatus`, `EventIdentity`, `EventProfile`, `SemanticElement`, `ProgramZone`, `DesignIntent`, `SemanticInvariant`, `ReasonerTrace`, `SemanticBrief`, `LLMCallRecord` |
| `domain/visual.py` | `VisualIntent` |
| `semantics/knowledge.py` | knowledge loader + referential validation, `PhraseIndex` (word-bounded, longest-first, negation-aware) |
| `semantics/knowledge/v1/*.yaml` | 12 families, 24 event types, 29 activities, 83 elements, 7 space types, 26 venues, priors |
| `semantics/intelligence.py` | `DesignIntelligence` |
| `semantics/{scope,programme,leakage,priors,reading}.py` | scope rule, programme inference, leak detector, priors, model contract |
| `visual/director.py`, `visual/templates.yaml` | `VisualDirector`, camera/composition templates by audience relationship and zone role |
| `providers/llm/structured.py` | `HttpStructuredGenerator`, `flat_schema` |
| protocol | `StructuredGenerator`, `StructuredResult` |
| API | `POST /api/semantics/interpret`, `GET /api/semantics/knowledge`, `GET /api/explorations/{id}/why/{element}` |

## 6. Wedding-specific assumptions removed

- Ceremony zones, sightline-to-ceremony invariant and per-tradition rites removed from
  `typology_defaults.yaml`; now selected only for `wedding_ceremony` with a stated tradition.
- `TYPOLOGY_KEYWORDS` no longer maps "wedding", "shaadi", "baraat", "nikah", "reception".
- Wedding ontology values carry `scope`; pruned elsewhere.
- Scene primary role no longer starts with `ceremony`; sightline edge only for focused audiences.
- Compiler fallbacks: no "processional route", no "ceremonial focus"; subject names the event.
- Views: shot list = programme zones, not `EVENT_CATALOGUE`.
- Synthesis rule 7 no longer uses a mandap as its example; mock cognition phrases are parametrised by the event's focus.
- Frontend no longer pre-selects Wedding / Mandap + Sangeeth.
- Anti-brief `qa_sacred` phrasing is rite-neutral; novelty archive keyed by event.

## 7. How unknown event types work

The brief's own noun phrase becomes the identity (`"Immersive astronomy storytelling
night"`, `known_type=false`). Activities are detected from cues (`projection surfaces`,
`live narration`, `informal seating`) and each activity contributes zones, relationships,
human activity, time of day and invariants. Audience relationship is decided by activity
precedence (immersive > surround > … ). Every scoped element is still judged, so a
mandap is forbidden without anyone writing that rule. A reasoning model, when enabled,
may add activities and zones; duplicates are rejected and model-inferred activities only
contribute optional zones. A new *known* type is a YAML entry — proven by
`test_adding_an_event_type_needs_no_code`.

## 8. How Design Intelligence works

Grounding → optional reasoning → merge, in that order of authority. The merge records
every rejected proposal on `reasoner.overridden` (e.g. *"zone 'bar_area' rejected:
duplicates an existing zone"*). Negative semantics are derived from element scope:
outside its scope an element is FORBIDDEN; with an unstated tradition a rite element is
CONTEXTUAL; an explicit request overrides scope and releases the generic element that
shares its place; an explicit exclusion ("no bar") removes the element and its zone.

## 9. How the LLM talks to the deterministic engine

Only through `StructuredGenerator.generate(stage, purpose, system, user, schema)`. The
adapter flattens the pydantic schema into a strict grammar, validates, retries once with
the validation errors, and returns `StructuredResult(value | None, LLMCallRecord)` —
never raises. The model proposes; deterministic code decides. The model never chooses a
genotype value, never removes a user request, never introduces an out-of-scope element,
and is never asked whether it leaked.

## 10. How the Visual Director works

For every selected concept: a hero intent from the audience-relationship template, one
intent per rendered programme zone from the zone-role template, and three orthographic
drawings. Subject, focus, zones, people, time of day and avoid-list come from the
semantics; material/structure readability from the genotype; lighting from the concept
when written. Event time outranks prose (a Haldi is a morning). Optional model refinement
touches only story/composition/layers/camera/people/light, is leak-checked, and every
field records its provenance. A final `_enforce` empties any field that names a
forbidden element.

## 11. How final prompts are generated

Deterministically from `VisualIntent` + concept + DNA: SUBJECT, IMAGE STORY, FOCAL POINT,
HUMAN ACTIVITY, COMPOSITION, then the architectural sections. Model-written sections that
name a forbidden element are dropped and listed on `semantic_leaks`. Negatives = anti-brief
tokens + concept anti-clichés + near-miss forbidden elements + the director's avoid-list,
minus anything the concept or the programme affirms (phrase-level). Views reuse the hero's
identity sections byte-for-byte.

## 12. Tests added

| File | Count | Scope |
|---|---|---|
| `test_semantics.py` | 38 | identity, A–J reading, traditions, explicit/negated intent, provenance, programme arithmetic, data-only extensibility, ontology scope |
| `test_semantic_isolation.py` | 56 | A–J through the full pipeline: independent forbidden-word regex over phenotype, scene, structured concept, visual intents, hero and view prompts; genotype scope; required zones built; semantic critic passes; subject/focus/shot list; cross-event differences |
| `test_structured_reasoning.py` | 10 | adapter (strict flat schema, validation retry, token record, failure returned), merge rules against a fake model, visual refinement cannot leak |
| `test_api.py` (+1) | 1 | tests never write into the user's session history |
| `capture_no_reference_baseline.py` | — | reproducible baseline capture with history |

Mutation check: a deliberately leaky writer that puts a mandap into a Sangeet is caught by
the validator (SEMANTIC_LEAK → repair), stripped by the compiler, and would fail the
isolation suite.

## 13. Test results

| Run | Result |
|---|---|
| Before the work (`7626ea7`) | 399 passed, 1 failed (`test_canonical_is_the_literal_interpretation`, pre-existing) |
| After (full suite, 14m47s) | **503 passed, 0 failed**, 1 skipped, 2 xfailed, 1 xpassed |
| Live LM Studio Sangeet (k=3) | COMPLETE; semantic reading by gemma-4-e4b in 54.5 s (469/1635 tokens); 3 concepts written; 0 ceremony words in final prompts; 2/3 pass validation (1 `IMPOSSIBLE_UNFLAGGED`, pre-existing structural check) |

Diversity (no-reference baselines, k=10, Vendi max 10): mean 9.79 before, 9.78 after;
minimum pairwise distance 0.58–0.73 against D_MIN 0.35. Under shared-archive pressure the
restaurant brief initially dropped to 7 geometries / 6 structural logics; semantic priors
were then moved from space weights to role-scaled solver bias, restoring 9 / 9 (before: 10 / 8).

## 14–17. Example traces

Generated by the pipeline; reproduced in the chat report. Sangeet (live, gemma-4-e4b),
Haldi, product launch and the unknown astronomy night.

## 18. Remaining limitations / technical debt

- Knowledge base breadth: 24 event types, 83 elements. Culturally specific elements for
  other regions (e.g. Chinese tea ceremony, Jewish chuppah) are not yet authored; the
  scope mechanism supports them as data.
- Lexical cue matching is English-only and can miss paraphrase; the reasoning model
  covers this only when enabled.
- `Typology` still exists as a space-form prior; ontology `typ_low` affinities are keyed by it.
- Venues beyond the original five are recorded but do not yet change site defaults.
- Visual Director refinement by a local 4B model costs one call per concept; off by default.
- The mock scene generator does not reason spatially; zone adjacency (`adjacent_to`) is
  not yet populated or used by the scene solver.
- Validation `IMPOSSIBLE_UNFLAGGED` still fails some real-model concepts (pre-existing check).
