# Reference fixture authoring guide (v1)

A fixture is one YAML file producing one `ReferenceDNA`. Fixtures are **editorial
content**, reviewed like the ontology — not scraped data.

## Required shape

```yaml
version: v1
identity: {reference_id, kind, display_name, aliases[], blurb}
traits:   [{id, dimension, statement, abstraction, salience, maps_to[], suggests[], evidence}]
literal_reading: {label, facet_values[], surface_tokens[], prevalence, naive_rendering}
surface_lexicon: [{token, category, transformed_to | justification}]
```

## The six authoring rules (enforced by `tests/test_reference_fixtures.py`)

1. **≥ 6 traits**, and ≥ 3 of the type's load-bearing dimensions at `salience ≥ 0.6`.
2. **No proper noun, no `display_name`, no own surface token** in any `statement`.
3. Every `suggests` value **resolves in the current ontology**.
4. `literal_reading.facet_values` has **≥ 2** entries, all resolvable.
5. **`naive_rendering` is present** — the paragraph a weak system would write. It is the
   denominator of transformation channel 5, and writing it forces the author to state
   the bad answer explicitly.
6. Every surface token has a `category`, and either a `transformed_to` **or** an
   explicit `justification` for why nothing transferable survives.

## Writing a good statement

A statement describes a **relation**, not an object, and must be understandable by a
designer who has never encountered the reference.

| Bad | Good |
|---|---|
| "candles on the tables" | "light originates below eye level, from many small sources" |
| "use a stepwell" | "descent is the arrival sequence" |
| "a Regency ballroom" | "a room whose purpose is collective display" |

`CONTEXT` dimensions (`ERA`, `CULTURAL_CONTEXT`, `TECHNOLOGICAL_CHARACTER`) must have
`maps_to: []`. They inform the phenotype; they never bias a facet.

## Salience vs abstraction

- **salience** — how central this is to the reference. Drives selection order.
- **abstraction** — 0 is a literal description, 1 is a transferable principle. Traits
  below the role's `abstraction_floor` are lifted or dropped.

Traits on a type's *usually-absent* dimensions have salience capped at 0.4 automatically.
