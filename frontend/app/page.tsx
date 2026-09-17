"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { BriefForm } from "../components/BriefForm";
import { ConceptCard } from "../components/ConceptCard";
import { ConceptPanel } from "../components/ConceptPanel";
import { SessionList } from "../components/SessionList";
import {
  BriefInput,
  Concept,
  createExploration,
  getConcepts,
  getSession,
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
  // `sessionId` is set both when a run finishes and when a past session is opened,
  // so the sidebar highlight is correct in either case.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  // How many concepts this run will produce. Known from the POST response, so
  // the grid can show that many placeholders before the first one lands.
  const [expected, setExpected] = useState(0);
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
        if (finished) {
          // the run is archived server-side at completion; pick it up
          setHistoryKey((k) => k + 1);
        } else {
          timer.current = setTimeout(() => poll(id, expected), 2500);
        }
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
        setBrief(input.brief);
      createExploration(input)
        .then((ex) => {
          setSessionId(ex.exploration_id);
          setExpected(ex.k ?? 10);
          setPhase("results");   // straight to the grid; cards fill in as they land
          poll(ex.exploration_id, ex.k ?? 10);
        })
        .catch((e) => {
          setError(String(e.message || e));
          setPhase("brief");
        });
    },
    [poll]
  );

  const openSession = useCallback(
    (id: string) => {
      if (timer.current) clearTimeout(timer.current);
      setError("");
      setOpen(null);
      getSession(id)
        .then((ex) => {
          const list: Concept[] = ex.concepts || [];
          setConcepts(list);
          setBrief(ex.brief?.raw_text || ex.brief?.text || "");
          setSessionId(id);
          setExpected(ex.k ?? list.length);
          setPhase("results");
          // A run that has not finished keeps going after you open it: pick the
          // live poll back up so the remaining concepts land in front of you
          // instead of freezing at whatever the last snapshot happened to hold.
          const finished = ex.status === "COMPLETE" || ex.status === "FAILED";
          setDone(finished && list.length > 0 && list.every(isSettled));
          if (!finished) poll(id, ex.k ?? list.length);
        })
        .catch((e) => setError(String(e.message || e)));
    },
    [poll]
  );

  const reset = () => {
    if (timer.current) clearTimeout(timer.current);
    setExpected(0);
    setPhase("brief");
    setConcepts([]);
    setOpen(null);
    setDone(false);
    setSessionId(null);
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

      <SessionList activeId={sessionId} onOpen={openSession} refreshKey={historyKey} />

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

        {phase === "results" && (
          <>
            <div className="results-head">
              <div>
                <div className="results-brief">{brief}</div>
                <div className="results-meta">
                  {done
                    ? `${written} concept${written === 1 ? "" : "s"}`
                    : `${settled} of ${Math.max(expected, concepts.length)} written…`}
                  {writer && <> · written by <b>{writer}</b></>}
                  {failed > 0 && <> · {failed} could not be written</>}
                </div>
              </div>
            </div>

            {!done && (
              <div className="bar" style={{ margin: "0 auto 28px" }}>
                <i style={{ width: `${Math.max(6, (settled / Math.max(1, expected || concepts.length)) * 100)}%` }} />
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
              {/* One placeholder per concept still to arrive, so the set has its
                  final shape from the first second rather than growing a card
                  at a time out of an empty page. */}
              {Array.from({ length: Math.max(0, expected - concepts.length) }).map((_, i) => (
                <div className="card-skeleton" key={`sk-${i}`}>
                  <div className="sk-no">
                    {String(concepts.length + i + 1).padStart(2, "0")}
                  </div>
                  <div className="sk-line" style={{ width: "72%" }} />
                  <div className="sk-line" style={{ width: "94%" }} />
                  <div className="sk-line" style={{ width: "86%" }} />
                  <div className="sk-line" style={{ width: "58%" }} />
                  <div className="sk-foot">Designing…</div>
                </div>
              ))}
            </div>
          </>
        )}
      </main>

      {open && (
        <ConceptPanel
          conceptId={open}
          sessionId={sessionId}
          onClose={() => setOpen(null)}
          onToast={setToast}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
