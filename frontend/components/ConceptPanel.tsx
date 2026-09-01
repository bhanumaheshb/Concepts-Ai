"use client";
import { useEffect, useState } from "react";
import { ConceptDetail, Shot, getConcept } from "../lib/api";

export function ConceptPanel({
  conceptId,
  onClose,
  onToast,
}: {
  conceptId: string;
  onClose: () => void;
  onToast: (m: string) => void;
}) {
  const [data, setData] = useState<ConceptDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getConcept(conceptId)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e.message || e)));
    return () => {
      alive = false;
    };
  }, [conceptId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const c = data?.structured_concept ?? null;
  const shots = data?.view_prompts ?? [];

  return (
    <div className="scrim" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="panel-head">
          <h2 className="panel-title">{data?.title || "Loading…"}</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="panel-body">
          {error && <div className="err">{error}</div>}
          {!data && !error && <p className="empty">Opening…</p>}

          {data && (
            <>
              {c?.concept_thesis && <p className="lede">{c.concept_thesis}</p>}

              {c?.design_story && (
                <section className="sec">
                  <h3>The idea</h3>
                  <p>{c.design_story}</p>
                </section>
              )}

              {c && c.spatial_sequence?.length > 0 && (
                <section className="sec">
                  <h3>How you move through it</h3>
                  <div className="steps">
                    {c.spatial_sequence.map((s, i) => (
                      <span key={i} style={{ display: "contents" }}>
                        {i > 0 && <span className="arrow">→</span>}
                        <span className="step" title={s.description}>
                          {s.step}
                        </span>
                      </span>
                    ))}
                  </div>
                </section>
              )}

              <section className="sec">
                <h3>At a glance</h3>
                <div className="pairs">
                  <Pair k="Language" v={data.headline_dna.architectural_language} />
                  <Pair k="Geometry" v={data.headline_dna.geometry} />
                  <Pair k="Structure" v={c?.structure?.structural_system || data.headline_dna.structural_logic} />
                  <Pair k="Material" v={c?.materials?.primary || data.headline_dna.material} />
                  <Pair k="Mood" v={c?.atmosphere || data.headline_dna.emotional_register} />
                </div>
              </section>

              {c?.program?.seating && (
                <section className="sec">
                  <h3>Seating &amp; capacity</h3>
                  <p>{c.program.seating}</p>
                </section>
              )}

              {c?.human_experience && (
                <section className="sec">
                  <h3>What it feels like</h3>
                  <p>{c.human_experience}</p>
                </section>
              )}

              {c && c.anti_cliches?.length > 0 && (
                <section className="sec">
                  <h3>Deliberately avoided</h3>
                  <ul className="bullets">
                    {c.anti_cliches.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="sec">
                <h3>Image prompts by area</h3>
                <p className="shots-intro">
                  One prompt per part of the space. Copy any of them into your image tool.
                </p>
                {shots.length === 0 && (
                  <p style={{ color: "var(--ink-3)" }}>
                    Prompts appear once this concept has finished being written.
                  </p>
                )}
                {shots.map((s, i) => (
                  <ShotRow key={s.view_key} shot={s} n={i + 1} onToast={onToast} />
                ))}
                {shots.length > 1 && (
                  <div className="linked">
                    <span className="dot-ok" />
                    <span>
                      All {shots.length} prompts share the same materials, structure and
                      lighting, so the images read as one place.
                    </span>
                  </div>
                )}
                {shots.length > 1 && (
                  <div style={{ marginTop: 12 }}>
                    <button
                      className="btn btn-ghost"
                      onClick={() => {
                        copy(
                          shots
                            .map((s) => `── ${s.view_label} ──\n${s.positive_prompt}`)
                            .join("\n\n")
                        );
                        onToast(`Copied all ${shots.length} prompts`);
                      }}
                    >
                      Copy every prompt
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ShotRow({ shot, n, onToast }: { shot: Shot; n: number; onToast: (m: string) => void }) {
  const [open, setOpen] = useState(n === 1);
  return (
    <div className="shot">
      <div
        className="shot-head"
        role="button"
        tabIndex={0}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpen((v) => !v)}
      >
        <span className="shot-name">
          <span className="shot-idx">{String(n).padStart(2, "0")}</span>
          {shot.view_label}
        </span>
        <span className={`chev ${open ? "open" : ""}`} aria-hidden>
          ▾
        </span>
      </div>
      {open && (
        <div className="shot-body">
          {shot.camera && <p className="shot-cam" style={{ marginBottom: 10 }}>{shot.camera}</p>}
          <pre className="prompt">{shot.positive_prompt}</pre>
          <div className="shot-actions">
            <button
              className="btn btn-ghost"
              onClick={() => {
                copy(shot.positive_prompt);
                onToast(`${shot.view_label} prompt copied`);
              }}
            >
              Copy prompt
            </button>
            {shot.negative_prompt && (
              <button
                className="btn-quiet"
                onClick={() => {
                  copy(shot.negative_prompt);
                  onToast("Negative prompt copied");
                }}
              >
                Copy negative prompt
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Pair({ k, v }: { k: string; v?: string }) {
  if (!v) return null;
  return (
    <div className="pair">
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}

function copy(text: string) {
  navigator.clipboard?.writeText(text).catch(() => {
    /* clipboard blocked; the text is on screen and selectable anyway */
  });
}
