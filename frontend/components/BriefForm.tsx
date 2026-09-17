"use client";
import { useEffect, useState } from "react";
import {
  BriefInput,
  getKnowledge,
  interpretBrief,
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
  // Nothing is pre-selected. A default here used to be sent as an explicit choice,
  // which turned every brief — a concert, a Haldi — into a Sangeet in a mandap.
  const [projectType, setProjectType] = useState("");
  const [eventType, setEventType] = useState("");
  const [tradition, setTradition] = useState("UNSPECIFIED");
  const [known, setKnown] = useState<{ key: string; label: string }[]>([]);
  const [reading, setReading] = useState<SemanticReading | null>(null);
  const [venueType, setVenueType] = useState("CONVENTION_SPACE");
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
      .then((k) => setKnown(k.event_types.map((e) => ({ key: e.key, label: e.label }))))
      .catch(() => setKnown([]));
  }, []);

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
          <input
            id="etype"
            className="input"
            list="event-suggestions"
            value={eventType}
            placeholder="Detected from the brief — or type any event"
            onChange={(e) => setEventType(e.target.value)}
          />
          <datalist id="event-suggestions">
            {known.map((e) => (
              <option key={e.key} value={e.label} />
            ))}
          </datalist>
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
            {VENUE_TYPES.map((t) => (
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
              project_type: projectType || undefined,
              event_type: eventType || undefined,
              tradition,
              venue_type: venueType,
              location: location.trim(),
              dimensions: dimensions.trim(),
              inspiration,
              references: refs,
            })
          }
        >
          {busy ? "Working…" : "Generate concepts"}
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
