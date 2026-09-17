"use client";
import { useEffect, useState } from "react";
import {
  BriefInput,
  CEREMONIAL_EVENTS,
  EVENT_TYPES,
  PROJECT_TYPES,
  ReferenceHit,
  searchReferences,
  TRADITIONS,
  TREND_MODES,
  VENUE_TYPES,
} from "../lib/api";

const SAMPLES = [
  "A 500-person luxury Sangeeth mandap with a dance floor and a bar counter, Jaipur.",
  "A 40-cover restaurant with an open kitchen and a long bar, in a converted warehouse.",
  "A garden pavilion for 150 guests that can be struck in a day.",
];

export function BriefForm({
  onSubmit,
  busy,
}: {
  onSubmit: (b: BriefInput) => void;
  busy: boolean;
}) {
  const [brief, setBrief] = useState("");
  const [projectType, setProjectType] = useState("WEDDING_MANDAP");
  const [eventType, setEventType] = useState("SANGEETH");
  const [tradition, setTradition] = useState("UNSPECIFIED");
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

  const ready = brief.trim().length >= 8;

  // Tradition only changes anything for a ceremony: it picks the focal element.
  // For a sangeeth or a reception the stage is the focus whatever the tradition.
  const ceremonial = CEREMONIAL_EVENTS.includes(eventType);
  const focus = TRADITIONS.find((t) => t.value === tradition)?.focus;

  // The areas the engine will photograph, mirroring EVENT_CATALOGUE on the server.
  const areas = (() => {
    const base = ["Entrance facade", "Pathway"];
    const tail = ["Seating", "Lounge", "Bar counter", "Side wall ambience"];
    if (ceremonial) return [...base, focus || "Ceremony focus", ...tail];
    if (eventType === "MEHENDI" || eventType === "HALDI")
      return [...base, "Seating", "Lounge", "Side wall ambience"];
    if (eventType === "GENERIC_EVENT") return [];
    return [
      ...base,
      "Performance stage",
      "Seating",
      ...(eventType === "SANGEETH" ? ["Dance floor"] : []),
      "Lounge",
      "Bar counter",
      "Side wall ambience",
    ];
  })();

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
          placeholder="e.g. A 500-person luxury Sangeeth mandap with a dance floor and a bar counter…"
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
          <select
            id="etype"
            className="select"
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
          >
            {EVENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="tradition">Tradition</label>
          <select
            id="tradition"
            className="select"
            value={tradition}
            disabled={!ceremonial}
            onChange={(e) => setTradition(e.target.value)}
          >
            {TRADITIONS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <div className="field-hint">
            {ceremonial
              ? focus
                ? `The ceremony is built around a ${focus.toLowerCase()}.`
                : "Sets the ceremonial focus of the space."
              : "Only applies to a ceremony — this event is built around a stage."}
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

      {areas.length > 0 && (
        <div className="field">
          <label>Each concept will be drawn for</label>
          <div className="chips" style={{ marginTop: 6 }}>
            {areas.map((a) => (
              <span key={a} className="chip" aria-disabled>
                {a}
              </span>
            ))}
          </div>
          <div className="field-hint">
            Optional areas appear only when your brief mentions them.
          </div>
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
              project_type: projectType,
              event_type: eventType,
              tradition: ceremonial ? tradition : undefined,
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
