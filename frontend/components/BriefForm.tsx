"use client";
import { useState } from "react";
import { BriefInput, PROJECT_TYPES, TREND_MODES } from "../lib/api";

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
  const [location, setLocation] = useState("");
  const [dimensions, setDimensions] = useState("");
  const [openInspo, setOpenInspo] = useState(false);
  const [inspiration, setInspiration] = useState("OFF");

  const ready = brief.trim().length >= 8;

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
          <label htmlFor="loc">Place &amp; season</label>
          <input
            id="loc"
            className="input"
            value={location}
            placeholder="Jaipur, May"
            onChange={(e) => setLocation(e.target.value)}
          />
        </div>
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
              {inspiration === "OFF"
                ? "Optional. Pulls in current references and works them into the concepts."
                : TREND_MODES.find((m) => m.value === inspiration)?.label}
            </div>
          </div>
          <span className={`chev ${openInspo ? "open" : ""}`} aria-hidden>
            ▾
          </span>
        </div>

        {openInspo && (
          <div className="inspo-body">
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
              location: location.trim(),
              dimensions: dimensions.trim(),
              inspiration,
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
