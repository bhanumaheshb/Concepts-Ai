"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { BriefForm } from "../components/BriefForm";
import { ConceptCard } from "../components/ConceptCard";
import { ConceptPanel } from "../components/ConceptPanel";
import {
  BriefInput,
  Concept,
  createExploration,
  getConcepts,
  hasFailed,
  isSettled,
  isWritten,
} from "../lib/api";

type Phase = "brief" | "working" | "results";

export default function Page() {
  const [phase, setPhase] = useState<Phase>("brief");
  const [brief, setBrief] = useState("");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2000);
    return () => clearTimeout(t);
  }, [toast]);

  /** Poll until every concept has been written. Cards appear as they land. */
  const poll = useCallback((id: string, expected: number) => {
    getConcepts(id)
      .then(({ concepts: list }) => {
        if (list.length) {
          setConcepts(list);
          setPhase("results");
        }
        // A card is finished when it is written OR has failed. Waiting on
        // `synthesis` alone would poll forever whenever the model is unreachable.
        const finished = list.length > 0 && list.every(isSettled);
        setDone(finished);
        if (!finished) timer.current = setTimeout(() => poll(id, expected), 2500);
      })
      .catch(() => {
        // The record does not exist yet — the run is still in its early stages.
        timer.current = setTimeout(() => poll(id, expected), 2500);
      });
  }, []);

  const start = useCallback(
    (input: BriefInput) => {
      setError("");
      setConcepts([]);
      setDone(false);
      setPhase("working");
      setBrief(input.brief);
      createExploration(input)
        .then((ex) => poll(ex.exploration_id, ex.k ?? 6))
        .catch((e) => {
          setError(String(e.message || e));
          setPhase("brief");
        });
    },
    [poll]
  );

  const reset = () => {
    if (timer.current) clearTimeout(timer.current);
    setPhase("brief");
    setConcepts([]);
    setOpen(null);
    setDone(false);
  };

  const written = concepts.filter(isWritten).length;
  const failed = concepts.filter(hasFailed).length;
  const settled = concepts.filter(isSettled).length;
  // Who actually wrote these. Provenance, not engine internals — and the one thing
  // that tells you at a glance whether the model or the fallback produced the text.
  const writer = concepts.find(isWritten)?.synthesis?.model || "";

  return (
    <>
      <header className="masthead shell" style={{ paddingBottom: 0 }}>
        <div className="wordmark">
          Concepts<em>.</em>
        </div>
        {phase === "results" && (
          <button className="btn btn-ghost" onClick={reset}>
            New brief
          </button>
        )}
      </header>

      <main className="shell">
        {phase === "brief" && (
          <>
            <BriefForm onSubmit={start} busy={false} />
            {error && (
              <div className="stage">
                <div className="err">{error}</div>
              </div>
            )}
          </>
        )}

        {phase === "working" && (
          <div className="working">
            <div className="working-line">
              Designing<span className="dots" />
            </div>
            <p className="working-sub">
              Working through the brief and writing each concept. This takes a couple of
              minutes.
            </p>
            <div className="bar">
              <i style={{ width: "12%" }} />
            </div>
          </div>
        )}

        {phase === "results" && (
          <>
            <div className="results-head">
              <div>
                <div className="results-brief">{brief}</div>
                <div className="results-meta">
                  {done
                    ? `${written} concept${written === 1 ? "" : "s"}`
                    : `${settled} of ${concepts.length} written…`}
                  {writer && <> · written by <b>{writer}</b></>}
                  {failed > 0 && <> · {failed} could not be written</>}
                </div>
              </div>
            </div>

            {!done && (
              <div className="bar" style={{ margin: "0 auto 28px" }}>
                <i style={{ width: `${Math.max(8, (settled / Math.max(1, concepts.length)) * 100)}%` }} />
              </div>
            )}

            <div className="grid">
              {concepts.map((c, i) => (
                <ConceptCard
                  key={c.concept_id}
                  concept={c}
                  n={i}
                  onOpen={() => setOpen(c.concept_id)}
                />
              ))}
            </div>
          </>
        )}
      </main>

      {open && (
        <ConceptPanel conceptId={open} onClose={() => setOpen(null)} onToast={setToast} />
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
