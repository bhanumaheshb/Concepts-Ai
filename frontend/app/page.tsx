"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { BriefForm } from "../components/BriefForm";
import { ConceptCard } from "../components/ConceptCard";
import { ConceptPanel } from "../components/ConceptPanel";
import { SessionList } from "../components/SessionList";
import {
  BriefInput,
  Concept,
  cancelExploration,
  createExploration,
  getConcepts,
  isFinalStatus,
  getExploration,
  getSession,
  SemanticReading,
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
  // What the engine designed this run AS. Read from the run itself, so it shows what
  // was actually used (including a reasoning model's contribution), not a re-guess.
  const [semantic, setSemantic] = useState<SemanticReading | null>(null);
  // "" while running; "stopping" once Stop is pressed; the final status once it ends
  const [runState, setRunState] = useState<"" | "stopping" | "stopped">("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const semanticFor = useRef<string | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2000);
    return () => clearTimeout(t);
  }, [toast]);

  /** Poll until every concept has been written. Cards appear as they land. */
  const poll = useCallback((id: string, expected: number) => {
    getConcepts(id)
      .then(({ concepts: list, status, cancelling }) => {
        if (cancelling) setRunState("stopping");
        if (list.length) {
          setConcepts(list);
          setPhase("results");
          if (semanticFor.current !== id) {
            // the reading never changes during a run, so fetch it once, not every poll
            semanticFor.current = id;
            getExploration(id)
              .then((ex) => ex.semantic && setSemantic(ex.semantic as SemanticReading))
              .catch(() => { semanticFor.current = null; });
          }
        }
        // A card is finished when it is written OR has failed. Waiting on
        // `synthesis` alone would poll forever whenever the model is unreachable.
        const stopped = status === "CANCELLED" || status === "INTERRUPTED";
        if (stopped) {
          setRunState("stopped");
          setExpected(list.length); // no placeholders for concepts that will never come
        }
        const finished = (list.length > 0 && list.every(isSettled)) || stopped
          || status === "FAILED";
        setDone(finished);
        if (finished) {
          // the run is archived server-side at completion; pick it up
          setHistoryKey((k) => k + 1);
        } else {
          timer.current = setTimeout(() => poll(id, expected), 2500);
        }
      })
      .catch(() => {
        // No live record: either the run has not reached stage 01 yet, or the backend
        // restarted and the run is gone. The saved session tells the two apart, so a
        // run cut off by a restart shows as stopped instead of spinning forever.
        getSession(id)
          .then((ex) => {
            if (ex.status === "INTERRUPTED" || ex.status === "CANCELLED") {
              const list: Concept[] = ex.concepts || [];
              setConcepts(list);
              setExpected(list.length);
              setRunState("stopped");
              setDone(true);
              setHistoryKey((k) => k + 1);
            } else {
              timer.current = setTimeout(() => poll(id, expected), 2500);
            }
          })
          .catch(() => {
            timer.current = setTimeout(() => poll(id, expected), 2500);
          });
      });
  }, []);

  const start = useCallback(
    (input: BriefInput) => {
      setError("");
      setConcepts([]);
      setSemantic(null);
      setRunState("");
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
          setSemantic((ex.semantic as SemanticReading) || null);
          setBrief(ex.brief?.raw_text || ex.brief?.text || "");
          setSessionId(id);
          setExpected(ex.k ?? list.length);
          setPhase("results");
          // A run that has not finished keeps going after you open it: pick the
          // live poll back up so the remaining concepts land in front of you
          // instead of freezing at whatever the last snapshot happened to hold.
          const finished = isFinalStatus(ex.status);
          const stopped = ex.status === "CANCELLED" || ex.status === "INTERRUPTED";
          setRunState(stopped ? "stopped" : "");
          if (stopped) setExpected(list.length);
          setDone((finished && list.length > 0 && list.every(isSettled)) || stopped);
          if (!finished) poll(id, ex.k ?? list.length);
        })
        .catch((e) => setError(String(e.message || e)));
    },
    [poll]
  );

  const stop = () => {
    if (!sessionId) return;
    setRunState("stopping");
    cancelExploration(sessionId)
      .then((r) => {
        if (r.status === "CANCELLED" || r.status === "COMPLETE" || r.status === "FAILED") {
          setRunState("stopped");
        }
      })
      .catch((e) => {
        setRunState("");
        setToast(String(e.message || e));
      });
  };

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
          <div style={{ display: "flex", gap: 10 }}>
            {!done && (
              <button
                className="btn btn-ghost btn-stop"
                onClick={stop}
                disabled={runState === "stopping"}
                title="Stops at the next step. A concept already being written finishes first."
              >
                {runState === "stopping" ? "Stopping…" : "Stop"}
              </button>
            )}
            <button className="btn btn-ghost" onClick={reset}>
              New brief
            </button>
          </div>
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
                {semantic && (
                  <div className="results-meta">
                    Designed as <b>{semantic.profile.identity.event_type_label}</b>
                    {semantic.profile.identity.event_family &&
                      ` · ${semantic.profile.identity.event_family.replace(/_/g, " ")}`}
                    {semantic.intent.primary_focus &&
                      ` · around the ${semantic.intent.primary_focus.toLowerCase()}`}
                    {semantic.reasoner.source !== "DETERMINISTIC" && semantic.reasoner.model &&
                      ` · read by ${semantic.reasoner.model}`}
                  </div>
                )}
                <div className="results-meta">
                  {runState === "stopped"
                    ? `Stopped · ${written} concept${written === 1 ? "" : "s"} written`
                    : runState === "stopping"
                      ? `Stopping after the current step… ${settled} of ${Math.max(expected, concepts.length)} written`
                      : done
                        ? `${written} concept${written === 1 ? "" : "s"}`
                        : `${settled} of ${Math.max(expected, concepts.length)} written…`}
                  {writer && <> · written by <b>{writer}</b></>}
                  {failed > 0 && runState !== "stopped" && <> · {failed} could not be written</>}
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
