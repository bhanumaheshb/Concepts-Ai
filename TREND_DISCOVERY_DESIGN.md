# Live Trend & Inspiration Discovery — design (V1)

Optional, brief-aware, cross-domain discovery that feeds the **existing** Reference
Intelligence pipeline. No second creative engine. No trend database. No image API.

---

## 1. Architecture

Six new stages, all **upstream of Reference Intelligence**, which is itself upstream of
the Divergence Engine. Nothing downstream changes.

```
TrendDiscoveryRequest
  TRD-00  Brief analysis      → TrendDomainPlan[]   (which domains, why, priority)
  TRD-01  Query generation    → queries per domain, built from the brief
  TRD-02  Provider discovery  → raw candidates      (TrendDiscoveryProvider)
  TRD-03  Signal extraction   → TrendSignal per candidate + freshness
  TRD-04  Scoring             → TrendScore (heuristic, mode-weighted)
  TRD-05  Diverse selection   → a spread across domains, not a top-N list
  TRD-06  Trend → ReferenceDNA
──────────────────────────────── boundary ────────────────────────────────
  EXISTING  Reference Intelligence → CreativePrincipleInjection
  EXISTING  Divergence Engine → 10 concepts
```

**The single integration rule:** a `TrendCandidate` becomes a `ReferenceDNA` and then it
is indistinguishable from a curated reference. Everything after TRD-06 is code that
already exists and is already tested.

## 2. Data models

| Model | Purpose |
|---|---|
| `TrendDomain` | 26 categories. Movies/TV are two of them, never the default. |
| `TrendMode` | `OFF · CURRENT_INSPIRATION · TRENDING_NOW · DESIGN_TRENDS · CULTURAL_MOMENT · SURPRISE_ME · CUSTOM` |
| `TrendFreshness` | `EMERGING · CURRENT · ESTABLISHED · DECLINING · EVERGREEN` |
| `SourceTier` | `OFFICIAL · MAJOR_PUBLICATION · TRADE_PUBLICATION · AGGREGATOR · COMMUNITY · SOCIAL` |
| `TrendEvidence` | url · source · tier · published · excerpt. **Every claim carries one.** |
| `TrendSignal` | recency · momentum · relevance · design_value · source_quality · novelty · cross_domain_potential |
| `TrendCandidate` | title · domain · summary · evidence[] · signal · freshness · principle_hints · why_selected · suggested_reference_type |
| `TrendDomainPlan` | domain · priority · rationale · queries[] |
| `TrendDiscoveryRequest` | mode · domains[] · max_candidates · region · event_date · seed |
| `TrendDiscoveryResult` | plan[] · candidates[] · selected[] · provider · is_mock · cached · generated_at |

## 3. Trend scoring — a ranking heuristic, stated as one

```
base = 0.26·relevance + 0.26·design_value + 0.16·source_quality
     + 0.12·recency   + 0.10·novelty      + 0.06·cross_domain
     + 0.04·momentum_adj

momentum_adj = momentum × min(1, corroboration/2) × source_quality
```

Momentum is deliberately the smallest term **and** gated: it only counts once two
independent sources corroborate. A single viral post cannot manufacture a trend.

**The anti-popularity rule (§9), implemented explicitly:**

```
if design_value < 0.35:  TrendScore = min(base, 0.45)
```

A hugely popular show with no transferable spatial content is capped below an obscure
architectural project with high design value. Mode re-weights the vector and
renormalises — `TRENDING_NOW` doubles recency+momentum, `DESIGN_TRENDS` doubles
design_value, `SURPRISE_ME` doubles novelty+cross_domain — but the cap always applies.

## 4. Domain selection

Deterministic, brief-driven, three inputs:

1. **Typology prior** — a table mapping each `Typology` to domain priorities.
2. **Keyword signals** — the brief's own words raise or lower domains.
3. **Mode adjustment** — `DESIGN_TRENDS` lifts the design cluster; `CULTURAL_MOMENT`
   lifts entertainment/culture; `CUSTOM` uses exactly the user's list; `SURPRISE_ME`
   deliberately injects two **low-affinity** domains — the far-retrieval trick from the
   architecture document, applied to domains instead of precedents.

Output is a ranked `TrendDomainPlan[]` with a stated rationale per domain. Nothing is
hardcoded to "movies".

## 5. Search strategy

Queries are generated per domain from the brief, never a global "trending design 2026":

```
{year} {register} {typology-phrase} {domain-phrase} trends
{year} {domain-phrase} {material/mood term}
current {domain-phrase} {location?}
```

Year comes from the request date. Location only appears when the user gave one (§15).
Capped at 3 queries per domain, 5 domains → ≤15 queries per discovery.

## 6. Source quality

Hostname → `SourceTier` → score. Official 1.0 · major publication 0.85 · trade 0.8 ·
aggregator 0.55 · community 0.4 · social 0.25. Unknown hosts default to aggregator.
Social evidence may *support* a candidate but cannot be its only evidence.

## 7. Freshness

Derived from the evidence set, never asserted:

| Status | Rule |
|---|---|
| `EMERGING` | newest ≤ 90d, ≤ 2 corroborating sources, momentum ≥ 0.6 |
| `CURRENT` | newest ≤ 270d, ≥ 2 sources |
| `ESTABLISHED` | ≥ 3 sources spanning > 1 year |
| `DECLINING` | newest > 540d |
| `EVERGREEN` | spans > 3 years with steady density |

A 2019 article cannot be labelled "trending now" — its newest evidence date forbids it.

## 8. Cross-domain discovery

Selection is **not** top-N by score. It is greedy max-marginal-relevance with a domain
term, the same shape as portfolio selection:

```
pick = argmax  0.62·score + 0.38·domain_novelty(candidate, chosen)
```

`domain_novelty` is 1.0 for an unused domain, decaying with each repeat. Target domain
shares come from the `TrendDomainPlan` priorities — adaptive, never a hardcoded 3/2/2/1.

## 9. Reference integration

`TrendReferenceAnalyzer` implements the **existing** `ReferenceAnalyzerProvider`
protocol. A candidate becomes a `ReferenceDNA`:

- `principle_hints` → `ReferenceTrait[]` (dimension, statement, abstraction, salience)
- proper nouns in title/summary → `SurfaceLexicon` (brand and project names blocked)
- the candidate's own visual cliché → `LiteralReading` + `naive_rendering`

From there: `build_injection` → `CreativePrincipleInjection` → the Divergence Engine.
Zero new concept-generation code. Transformation scoring, compatibility, synthesis,
the originality critic and the cliché quota all apply unchanged.

## 10. API

```
POST /api/trends/discover     → TrendDiscoveryResult   (callable alone, before Generate)
GET  /api/trends/domains      → the domain vocabulary + mode list
POST /api/trends/plan         → TrendDomainPlan[] only (cheap, no provider call)
POST /api/explorations        → + optional `trend: TrendBlock | null`
GET  /api/explorations/{id}/trend-debug
```

## 11. UI

An `INSPIRATION` block in the existing sidebar: mode radio, domain chips (CUSTOM only),
`DISCOVER INSPIRATION`, then candidate cards showing domain · freshness · score · **why
selected** · source, each with `USE AS INSPIRATION`. Selected candidates flow into the
existing reference chips. A `TREND DEBUG` tab shows plan → queries → candidates →
scores → selection.

## 12. Mock mode

`MockTrendProvider` with 6 deterministic fixture files. Every mock candidate carries
`is_mock=true`, its evidence source reads `MOCK FIXTURE`, and the UI shows a
`MOCK TREND DATA` banner. Mock data must never be mistakable for live data.

## 13. Caching

In-memory, TTL 6h, key = `sha256(normalised_query | region | date_bucket | mode)`.
Reference analysis caches separately by content hash. One exploration never issues the
same query twice.

## 14. Testing

`trend OFF is byte-identical` (the critical regression) · domain selection · query
generation · source ranking · scoring incl. the anti-popularity cap · freshness
classification · domain diversity · cross-domain discovery · trend→ReferenceDNA ·
trend→injection · transformation · portfolio diversity · caching · provider independence.

## 15. Implementation order

Exactly the user's order. Live web search is **last** and is not in V1.

## 16. V1 / V2 boundary

**V1** — everything above with `MockTrendProvider` only. Deterministic, offline, tested.

**V2** — `WebSearchTrendProvider` (live), evidence extraction from real pages, momentum
from cross-source corroboration over time, region-aware ranking, trend memory with
expiry, and visual/moodboard references.
