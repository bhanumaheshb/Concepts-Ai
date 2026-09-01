# WebSearchTrendProvider — implementation plan

Milestone scope: replace the *provider* only. Nothing above the provider boundary changes.

## 0. Honest statement of what is and is not available

Verified by inspection before writing code:

| Fact | Status |
|---|---|
| Backend process has outbound HTTPS | **yes** (`https://example.com` → 200) |
| A search-API key is configured | **no** — `.env` has none, environment has none |
| The application can therefore call a live search API today | **no** |

Consequence, stated plainly: this milestone ships a **real provider that cannot be
exercised against a live search API in this environment**. To avoid the failure the
brief explicitly warns about — *"do not claim live trends unless the system actually
retrieved and verified live evidence"* — the plan is:

1. Implement `WebSearchTrendProvider` against a `SearchBackend` seam.
2. Ship `HttpSearchBackend` (keyed, real HTTP, untested here — no key) and
   `RecordedSearchBackend` (replays **genuinely retrieved** web results).
3. Populate the recorded corpus from real searches and real page fetches performed
   during this milestone, preserving real URLs, publishers, titles and — where the page
   actually stated one — real publication dates.
4. Every claim in the final report is labelled by which of these produced it.

The corpus is real evidence. The *transport* is recorded rather than live.

## 1. Current provider interface (as built, verified)

```python
class TrendDiscoveryProvider(Protocol):
    name: str
    is_live: bool
    def is_configured(self) -> bool: ...
    def discover(self, *, queries, domain, limit, seed=0) -> list[TrendCandidate]: ...
```

`MockTrendProvider` additionally exposes `domains_available()`, which
`composition.provider_status()` and `/api/trends/domains` both call — so the live
provider must expose it too.

## 2. Current mock flow

`TrendService.discover` → for each `TrendDomainPlan`: cache key from
`(joined queries, region, mode, date bucket)` → on miss call
`provider.discover(queries=…, domain=…, limit=3)` → candidates are then scored by
`score_candidate`, classified by `classify_freshness`, explained by `explain`, and
selected by `select_diverse`. **All of that stays.**

## 3. Exact replacement point

One line in `composition.py`:

```python
trends=TrendService(ont, build_trend_provider(settings, ont))
```

`build_trend_provider` returns `MockTrendProvider` unless `TREND_PROVIDER=web`.
No other call site changes.

## 4. Web search strategy

Queries come from the **existing TRD-01 generator** — unchanged, brief-aware,
domain-aware. The provider receives them and does not invent its own. Region is passed
through and appears in the query only when the user supplied it.

Per domain: issue up to `MAX_TREND_QUERIES_PER_DOMAIN` queries, collect results, and
stop early once `MAX_CANDIDATES_PER_DOMAIN` survive extraction.

## 5. Evidence extraction

From a search result: `url`, `title`, `publisher` (registrable domain → display name),
`excerpt` (snippet), `retrieved_at` (now), `evidence_type=SEARCH_RESULT`.

Dates are the hard part and are **never fabricated**:

- a date in the result metadata is used as-is;
- a date parsed from the URL path (`/2026/03/11/`) is used;
- an unresolvable fragment ("Dec 16" with no year) yields `published_at = null`;
- optional page fetch (`TREND_FETCH_PAGES=true`) upgrades `SEARCH_RESULT` evidence to
  `PAGE` evidence with a verified date. Off by default: it is slow and it is scraping.

## 6. Source validation

`tier_for()` already exists and is reused. Added on top:

- a **deny list** of SEO/content-farm and AI-content signals → tier forced to `SOCIAL`
  and the source cannot be a candidate's only evidence;
- vendor/self-promotional hosts (a supplier blog writing about its own category) are
  demoted to `COMMUNITY`;
- unknown hosts stay `AGGREGATOR`, as today.

Nothing is auto-rejected; weak sources become weak corroboration.

## 7. Freshness

Reuses `classify_freshness` unchanged. The provider adds two **new optional** fields so
the classifier's confidence is visible rather than implied:

- `freshness_confidence` — from how many evidence items carry a real date;
- `freshness_evidence` — the dated URLs the classification rests on.

A candidate with **no dated evidence** is marked `low_confidence` and is excluded from
selection in live mode. It is not silently called `CURRENT`.

## 8. Deduplication and syndication

Normalise → `canonical_url` (strip `utm_*`, fragments, trailing slash), `norm_title`
(lowercased, punctuation stripped, stopwords removed).

Two evidence items collapse to one signal when: same canonical URL, **or** title
similarity ≥ 0.85, **or** (title similarity ≥ 0.7 **and** excerpt similarity ≥ 0.7)
across different hosts — the syndication case. Independence is counted over
*registrable domains after* collapsing.

## 9. Design value — the unresolved problem, addressed transparently

No invented number. `estimate_design_value()` returns
`(estimate | None, confidence, features, reason)` from four evidence-derived features:

| Feature | Derived from |
|---|---|
| `spatial_lexicon` | density of curated spatial/material/light/geometry terms in title+excerpt |
| `transferability` | the excerpt describes a **relation**, reusing the existing `relates()` predicate from the abstraction ladder |
| `domain_prior` | how design-bearing the domain is |
| `source_signal` | design trade/major publication tier |

`confidence` falls with thin excerpts, single evidence and unknown tiers. Below
`DESIGN_VALUE_MIN_CONFIDENCE` the candidate is flagged `DESIGN_VALUE_UNCERTAIN`,
`design_value_estimate = None`, and it is barred from selection. The existing
`design_value < 0.35 → cap 0.45` rule continues to apply on top.

## 10. Trend score

Unchanged. The provider supplies evidence-backed signal components; `scoring.py` still
owns ranking. Momentum is computed from **independent recent** evidence only, and is
left low when evidence is insufficient rather than guessed.

## 11. Entity resolution

An article title is not a reference. `resolve_entity()` turns
*"Top Experiential Design Trends Shaping Events in 2026"* into a clean signal identity
(`"experiential event design"`, plus a normalised claim) before it reaches
`candidate_to_dna`. Raw titles never enter the creative engine.

## 12. Caching, rate limits, failure

Existing `TrendCache` reused. New config: `MAX_TREND_QUERIES`, `MAX_TREND_CANDIDATES`,
`MAX_SOURCES_PER_CANDIDATE`, `SEARCH_TIMEOUT_S`, `SEARCH_RETRIES`.

Failure is **per domain**: one domain's search failing leaves the others intact, and the
failure is recorded in the result. If every domain fails, the result carries
`TREND_DISCOVERY_UNAVAILABLE` and the UI offers **Continue Without Trends**. An
exploration is never failed by a trend query.

## 13. Security

Retrieved text is data. Extraction pulls only title/date/publisher/excerpt; nothing
retrieved is ever placed in an instruction position, and prompt-injection markers in a
page are stripped and logged, not obeyed.

## 14. Tests

Nine files as specified, all offline via `RecordedSearchBackend` and a
`FailingSearchBackend`. No test touches the network.

## 15. Rollout

`TREND_PROVIDER=mock` (default) → `recorded` (real corpus, deterministic) → `web`
(keyed, live). Trend OFF stays byte-identical at every step.

---

# BUILT — outcome

## Three evidence states, never conflated

The original design had one boolean (`is_mock`). That was not enough, and conflating
"not mock" with "live" is exactly the claim the brief forbids. The system now reports
three states:

| State | `is_mock` | `is_live` | Evidence | Banner |
|---|---|---|---|---|
| `MOCK` | true | false | invented fixtures | MOCK TREND DATA |
| `RECORDED` | false | false | **real** URLs/publishers, replayed | RECORDED EVIDENCE — real sources, recorded transport |
| `LIVE` | false | true | real, retrieved now | LIVE WEB DISCOVERY |

`TREND_PROVIDER=web` with no key stays `is_live=true, is_configured=false` and reports
`TREND_DISCOVERY_UNAVAILABLE` — it never falls back to fixtures and calls them live.

## Two corrections made during implementation

1. **`classify_freshness` returned `CURRENT` when no evidence had a date.** That asserted
   currency from nothing — the precise failure the brief names. Added
   `TrendFreshness.UNDATED`; a signal with no dated evidence now reads UNDATED.
2. **`SOURCE_WEIGHT` had no `"REFERENCE"` entry** (a latent bug left by the Reference
   milestone). It raised `KeyError` the first time a discovered trend's literal reading
   overlapped a curated cliché by ≥ MATCH_THRESHOLD. Fixed, with a test that asserts
   every `ClicheCluster.evidence` kind has a merge weight.

## What bars a signal from selection

Mode-dependent, because what bars a claim depends on what the mode claims:

* **always** — design value that could not be estimated from the evidence (that number
  feeds the ranking; a guess would corrupt it);
* **recency-claiming modes only** (`TRENDING_NOW`, `CULTURAL_MOMENT`) — undated evidence.

Measured on the recorded corpus: `DESIGN_TRENDS` selects 3 of 6 signals (all correctly
labelled UNDATED); `TRENDING_NOW` selects **0 of 6** and says why for each.

## A third correction: a test-isolation defect this milestone exposed

`test_pipeline.py` — the divergence acceptance suite — shared the session-scoped
container, and therefore shared the **novelty archive** with every other test that runs
an exploration (notably `test_api.py`, which drives real explorations through the same
container). The archive steers the allocator, so a hard threshold like
">= 7 distinct structural logics out of 10" was being measured against whatever earlier
tests happened to leave behind.

Symptom: `pavilion` failed in a full-suite run (6 of 7) and passed in isolation,
reproducibly, in two separate full runs. Fixed the same way
`test_no_reference_regression` was: the acceptance tests now run on a module-scoped
pipeline with their **own** `InMemoryStore`, so the archive contains only their own runs.
Pre-existing and unrelated to trend discovery — the milestone only made it visible.

## Freshness benchmark

**18/20 = 90%.** Both misses are recorded as `xfail`, not tuned away:

* `b10` — the code returns EVERGREEN on span > 1095d; §7 says EVERGREEN needs
  "steady density", which the code does not test. A real spec/code gap.
* `b18` — §7 caps EMERGING at "≤ 2 corroborating sources", so a 3-source burst reads
  CURRENT. The code follows the published rule; my expectation did not.

No threshold was moved to raise this number.
