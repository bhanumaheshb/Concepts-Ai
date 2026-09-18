"use client";
import { useEffect, useMemo, useState } from "react";
import { Box, Layers } from "lucide-react";
import {
  BriefInput,
  getKnowledge,
  interpretBrief,
  KnowledgeCatalogue,
  PROJECT_TYPES,
  ReferenceHit,
  searchReferences,
  SemanticReading,
  TRADITIONS,
  TREND_MODES,
  VENUE_TYPES,
} from "../lib/api";

const SAMPLES = [
  "A 500-person luxury Sangeet in Jaipur with a large dance floor, a live performance stage and a bar.",
  "A minimalist technology product launch for 300 guests.",
  "An immersive astronomy storytelling night for 350 people with projection surfaces, live narration and informal seating.",
];

export function BriefForm({
  onSubmit,
  busy,
}: {
  onSubmit: (b: BriefInput) => void;
  busy: boolean;
}) {
  const [brief, setBrief] = useState("");
  const [outputMode, setOutputMode] = useState<"CONCEPT" | "SET_3D">("CONCEPT");
  // Nothing is pre-selected. A default here used to be sent as an explicit choice,
  // which turned every brief — a concert, a Haldi — into a Sangeet in a mandap.
  const [projectType, setProjectType] = useState("");
  const [eventType, setEventType] = useState("");
  const [tradition, setTradition] = useState("UNSPECIFIED");
  const [catalogue, setCatalogue] = useState<KnowledgeCatalogue | null>(null);
  const [reading, setReading] = useState<SemanticReading | null>(null);
  const [venueType, setVenueType] = useState("");
  const [location, setLocation] = useState("");
  const [dimensions, setDimensions] = useState("");
  const [openInspo, setOpenInspo] = useState(false);
  const [inspiration, setInspiration] = useState("OFF");
  const [refQuery, setRefQuery] = useState("");
  const [refHits, setRefHits] = useState<ReferenceHit[]>([]);
  const [refs, setRefs] = useState<string[]>([]);

  // Debounced lookup. Curated references resolve by alias, so partial titles work.
  useEffect(() => {
    const q = refQuery.trim();
    if (q.length < 2) {
      setRefHits([]);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      searchReferences(q)
        .then((r) => live && setRefHits(r.results.slice(0, 5)))
        .catch(() => live && setRefHits([]));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [refQuery]);

  const addRef = (name: string) => {
    setRefs((prev) => (prev.includes(name) || prev.length >= 4 ? prev : [...prev, name]));
    setRefQuery("");
    setRefHits([]);
  };

  useEffect(() => {
    getKnowledge()
      .then(setCatalogue)
      .catch(() => setCatalogue(null));
  }, []);

  // "Type of space" narrows what is worth suggesting next. It never decides what the
  // event is — the brief does — so an empty space type narrows nothing.
  const space = catalogue?.spaces.find((s) => s.value === projectType);
  const eventOptions = useMemo(() => {
    const all = (catalogue?.event_types || []).map((e) => ({ key: e.key, label: e.label, family: e.family }));
    if (!space || space.families.length === 0) return all;
    return all.filter((e) => space.families.includes(e.family));
  }, [catalogue, space]);
  const venueOptions = useMemo(() => {
    if (!catalogue) return VENUE_TYPES;
    const keys = space && space.venues.length ? space.venues : Object.keys(catalogue.venues);
    return keys.map((k) => ({ value: k, label: catalogue.venues[k] || k }));
  }, [catalogue, space]);

  // Changing the space clears choices that no longer belong to it. A typed event that
  // is not in the catalogue is the user's own and is always kept.
  useEffect(() => {
    if (!catalogue) return;
    const typed = eventType.trim().toLowerCase();
    const knownEvent = catalogue.event_types.find((e) => e.label.toLowerCase() === typed);
    if (knownEvent && !eventOptions.some((e) => e.key === knownEvent.key)) setEventType("");
    if (venueType && !venueOptions.some((v) => v.value === venueType)) setVenueType("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectType, catalogue]);

  // Live reading of the brief: what the engine understands before it designs anything.
  // Deterministic and fast, so it can follow typing.
  useEffect(() => {
    const text = brief.trim();
    if (text.length < 8) {
      setReading(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      interpretBrief({ brief: text, event_type: eventType, tradition, project_type: projectType })
        .then((r) => live && setReading(r))
        .catch(() => live && setReading(null));
    }, 450);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [brief, eventType, tradition, projectType]);

  const ready = brief.trim().length >= 8;
  const ident = reading?.profile.identity;
  const zones = (reading?.programme || []).filter((z) => z.priority !== "optional");
  const excluded = (reading?.profile.elements || []).filter(
    (e) =>
      e.status === "FORBIDDEN" &&
      (e.provenance === "USER_EXPLICIT" || e.rationale.includes("neighbouring"))
  );
  const focus = TRADITIONS.find((t) => t.value === tradition)?.focus;

  return (
    <div className="stage">
      <div className="concept-modes" role="group" aria-label="Concept mode">
        <button type="button" aria-pressed={outputMode === "CONCEPT"} disabled={busy} onClick={() => setOutputMode("CONCEPT")}><Layers size={24} />Concepts</button>
        <button type="button" aria-pressed={outputMode === "SET_3D"} disabled={busy} onClick={() => setOutputMode("SET_3D")}><Box size={28} />3D Concepts</button>
      </div>
      <h1 className="stage-lead">What are you designing?</h1>
      <p className="stage-sub">
        Describe it the way you would to a colleague. You will get a set of distinct
        concepts, each with image prompts for every part of the space.
      </p>

      <div className="field">
        <label htmlFor="brief">Your brief</label>
        <textarea
          id="brief"
          className="textarea"
          value={brief}
          placeholder="e.g. A 500-person Sangeet in Jaipur with a dance floor, a performance stage and a bar…"
          onChange={(e) => setBrief(e.target.value)}
        />
        <div style={{ marginTop: 8, display: "flex", gap: 14, flexWrap: "wrap" }}>
          {SAMPLES.map((s, i) => (
            <button key={i} className="btn-quiet" type="button" onClick={() => setBrief(s)}>
              Try example {i + 1}
            </button>
          ))}
        </div>
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="ptype">Type of space</label>
          <select
            id="ptype"
            className="select"
            value={projectType}
            onChange={(e) => setProjectType(e.target.value)}
          >
            {PROJECT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="etype">What is the event</label>
          <EventCombo value={eventType} options={eventOptions} onChange={setEventType} />
          {space && space.families.length > 0 && (
            <div className="field-hint">
              Suggestions for {space.label.toLowerCase()} — any other event can still be typed.
            </div>
          )}
        </div>
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="tradition">Tradition</label>
          <select
            id="tradition"
            className="select"
            value={tradition}
            onChange={(e) => setTradition(e.target.value)}
          >
            {TRADITIONS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <div className="field-hint">
            {focus
              ? `Used only where the event has a rite: a ceremony is then built around a ${focus.toLowerCase()}.`
              : "Never assumed. Rite-specific elements appear only when a tradition is stated."}
          </div>
        </div>
        <div className="field">
          <label htmlFor="venue">Venue</label>
          <select
            id="venue"
            className="select"
            value={venueType}
            onChange={(e) => setVenueType(e.target.value)}
          >
            <option value="">Not specified</option>
            {venueOptions.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="loc">Place &amp; season</label>
          <input
            id="loc"
            className="input"
            value={location}
            placeholder="Jaipur, May"
            onChange={(e) => setLocation(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="dims">Size of the space</label>
          <input
            id="dims"
            className="input"
            value={dimensions}
            placeholder="Optional — e.g. 34 x 24 m"
            onChange={(e) => setDimensions(e.target.value)}
          />
        </div>
      </div>

      {ident && (
        <div className="field reading">
          <label>Understood as</label>
          <div className="reading-head">
            <strong>{ident.event_type_label}</strong>
            {ident.event_family && <span> · {ident.event_family.replace(/_/g, " ")}</span>}
            {ident.tradition && <span> · {ident.tradition}</span>}
            {!ident.known_type && <span className="reading-tag">new event — inferred from its activities</span>}
          </div>
          {reading?.intent.primary_focus && (
            <div className="field-hint">
              Organised around the {reading.intent.primary_focus.toLowerCase()}
              {reading.profile.audience_relationship !== "none" &&
                ` · attention is ${reading.profile.audience_relationship}`}
            </div>
          )}
          <div className="chips" style={{ marginTop: 8 }}>
            {zones.map((z) => (
              <span
                key={z.key}
                className="chip"
                aria-disabled
                title={`${z.priority} · ${z.provenance.toLowerCase().replace(/_/g, " ")} · ${z.rationale}`}
              >
                {z.label}
              </span>
            ))}
          </div>
          {excluded.length > 0 && (
            <div className="field-hint" style={{ marginTop: 8 }}>
              Will not contain: {excluded.map((e) => e.label.toLowerCase()).join(", ")}
            </div>
          )}
          {(reading?.intent.uncertainties || []).slice(0, 2).map((u) => (
            <div key={u} className="field-hint reading-warn">
              {u}
            </div>
          ))}
        </div>
      )}

      <div className="inspo">
        <div
          className="inspo-head"
          role="button"
          tabIndex={0}
          onClick={() => setOpenInspo((v) => !v)}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpenInspo((v) => !v)}
        >
          <div>
            <div className="inspo-title">Add inspiration</div>
            <div className="inspo-hint">
              {refs.length
                ? refs.join(" · ")
                : inspiration === "OFF"
                  ? "Optional. Name a film, series or place — the idea behind it is worked in, never its props."
                  : TREND_MODES.find((m) => m.value === inspiration)?.label}
            </div>
          </div>
          <span className={`chev ${openInspo ? "open" : ""}`} aria-hidden>
            ▾
          </span>
        </div>

        {openInspo && (
          <div className="inspo-body">
            <div className="field">
              <label htmlFor="ref">Reference</label>
              <input
                id="ref"
                className="input"
                value={refQuery}
                placeholder="Stranger Things, a stepwell, brutalism…"
                autoComplete="off"
                onChange={(e) => setRefQuery(e.target.value)}
              />
              {refHits.length > 0 && (
                <ul className="ref-hits">
                  {refHits.map((h) => (
                    <li key={h.reference_id}>
                      <button type="button" onClick={() => addRef(h.display_name)}>
                        <span className="ref-name">{h.display_name}</span>
                        <span className="ref-blurb">{h.blurb}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {refs.length > 0 && (
                <div className="chips" style={{ marginTop: 10 }}>
                  {refs.map((r) => (
                    <button
                      key={r}
                      type="button"
                      className="chip"
                      aria-pressed
                      onClick={() => setRefs((p) => p.filter((x) => x !== r))}
                      title="Remove"
                    >
                      {r} ✕
                    </button>
                  ))}
                </div>
              )}
              <div className="field-hint">
                Up to four. The engine transfers the underlying principle — a
                reference&rsquo;s own vocabulary is blocked, not copied.
              </div>
            </div>

            <div className="field">
              <label>Or pull from what is current</label>
            </div>
            <div className="chips">
              <button
                type="button"
                className="chip"
                aria-pressed={inspiration === "OFF"}
                onClick={() => setInspiration("OFF")}
              >
                None
              </button>
              {TREND_MODES.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  className="chip"
                  aria-pressed={inspiration === m.value}
                  onClick={() => setInspiration(m.value)}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="actions">
        <button
          className="btn btn-primary btn-lg"
          disabled={!ready || busy}
          onClick={() =>
            onSubmit({
              brief: brief.trim(),
              output_mode: outputMode,
              project_type: projectType || undefined,
              event_type: eventType || undefined,
              tradition,
              venue_type: venueType || undefined,
              location: location.trim(),
              dimensions: dimensions.trim(),
              inspiration,
              references: refs,
            })
          }
        >
          {busy ? "Working…" : outputMode === "SET_3D" ? "Generate 3D concepts" : "Generate concepts"}
        </button>
        {!ready && brief.length > 0 && (
          <span style={{ color: "var(--ink-3)", fontSize: 13 }}>
            A sentence or two is enough.
          </span>
        )}
      </div>
    </div>
  );
}

/** Free-text event field with suggestions. Replaces a native <datalist>, whose popup
 *  the browser draws detached from the field and outside the page's styling. */
function EventCombo({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { key: string; label: string }[];
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const q = value.trim().toLowerCase();
  const matches = (q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options).slice(0, 8);
  const exact = options.some((o) => o.label.toLowerCase() === q);
  const show = open && matches.length > 0 && !exact;

  const pick = (label: string) => {
    onChange(label);
    setOpen(false);
    setActive(-1);
  };

  return (
    <div className="combo">
      <input
        id="etype"
        className="input"
        role="combobox"
        aria-expanded={show}
        aria-controls="etype-list"
        aria-autocomplete="list"
        autoComplete="off"
        value={value}
        placeholder="Auto-detect, or type any event"
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        // delay so a click on an option lands before the list unmounts
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (!show) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((i) => Math.min(matches.length - 1, i + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(0, i - 1));
          } else if (e.key === "Enter" && active >= 0) {
            e.preventDefault();
            pick(matches[active].label);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {value && (
        <button type="button" className="combo-clear" aria-label="Clear event" onClick={() => onChange("")}>
          ✕
        </button>
      )}
      {show && (
        <ul className="combo-list" id="etype-list" role="listbox">
          {matches.map((o, i) => (
            <li
              key={o.key}
              role="option"
              aria-selected={i === active}
              className={`combo-item${i === active ? " is-active" : ""}`}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(o.label);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
