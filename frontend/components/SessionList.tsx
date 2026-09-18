"use client";
import { useCallback, useEffect, useState } from "react";
import { Session, isRunning, isStopped, listSessions, deleteSession } from "../lib/api";
import { Trash2 } from "lucide-react";

/** Past runs, kept on disk by the backend so they outlive a restart.
 *  Numbered oldest-first, so Session 1 stays Session 1 as new runs arrive.
 *  Deleted entries retain their server-side snapshot for recovery. */
const COLLAPSE_KEY = "sessions-collapsed";
const PHONE = "(max-width: 760px)";   // matches the stacked layout in globals.css

export function SessionList({
  activeId,
  onOpen,
  refreshKey,
  onDelete,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
  refreshKey: number;
  onDelete: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [collapsed, setCollapsedState] = useState(false);
  const setCollapsed = (value: boolean) => {
    setCollapsedState(value);
    try { localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0"); } catch { /* storage unavailable */ }
  };

  // On a phone the list sits ABOVE the brief form, so starting open buries the form
  // under every past session. Start collapsed there; otherwise honour the last choice.
  // Read after mount: the server render has no window, and matching it avoids a
  // hydration mismatch.
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(COLLAPSE_KEY); } catch { /* storage unavailable */ }
    if (saved !== null) setCollapsedState(saved === "1");
    else if (window.matchMedia(PHONE).matches) setCollapsedState(true);
  }, []);
  const [busy, setBusy] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  // Two-step delete: a single stray click once cost a real session. The first click
  // arms the button for a few seconds; only a second click deletes.
  const [confirming, setConfirming] = useState<string | null>(null);
  useEffect(() => {
    if (!confirming) return;
    const t = setTimeout(() => setConfirming(null), 4000);
    return () => clearTimeout(t);
  }, [confirming]);
  const [error, setError] = useState("");

  const remove = async (id: string) => {
    setDeleting(id);
    setError("");
    try {
      await deleteSession(id);
      setSessions((rows) => rows.filter((s) => s.exploration_id !== id));
      onDelete(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete session.");
    } finally {
      setDeleting(null);
    }
  };

  const load = useCallback(() => {
    listSessions()
      .then((r) => setSessions(r.sessions))
      .catch(() => setSessions([]))
      .finally(() => setBusy(false));
  }, []);

  // The backend snapshots a run to disk every few seconds, so re-reading the list
  // on a timer is what makes a row appear the moment the first concept is written
  // and climb from "1 of 10" to "10 of 10" without anyone reloading the page.
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load, refreshKey]);

  if (collapsed) {
    return (
      <button
        className="sessions-reopen"
        onClick={() => setCollapsed(false)}
        title="Show past sessions"
      >
        ☰ Sessions{sessions.length ? ` (${sessions.length})` : ""}
      </button>
    );
  }

  return (
    <aside className="sessions">
      <div className="sessions-head">
        <span>Sessions</span>
        <button className="sessions-hide" onClick={() => setCollapsed(true)} title="Hide">
          ✕
        </button>
      </div>

      {busy && <div className="sessions-empty">Loading…</div>}

      {!busy && sessions.length === 0 && (
        <div className="sessions-empty">
          Nothing saved yet. Every run you generate is kept here.
        </div>
      )}

      <ul className="sessions-list">
        {sessions.map((s) => (
          <li key={s.exploration_id} className="session-item">
            <button
              className={`session-row${s.exploration_id === activeId ? " is-active" : ""}`}
              onClick={() => {
                onOpen(s.exploration_id);
                // on a phone, get the list out of the way of the results just opened
                if (window.matchMedia(PHONE).matches) setCollapsedState(true);
              }}
            >
              <span className="session-no">
                Session {s.session_no}
                {isRunning(s) && <i className="session-live" title="Still running" />}
              </span>
              <span className="session-brief">{s.brief || "Untitled brief"}</span>
              <span className="session-meta">
                {isRunning(s)
                  ? `${s.written} of ${s.k ?? s.concepts} written…`
                  : isStopped(s)
                    ? `Stopped · ${s.written} of ${s.k ?? s.concepts} written`
                    : `${s.concepts} concept${s.concepts === 1 ? "" : "s"}`}
                {s.started_at
                  ? ` · ${new Date(s.started_at * 1000).toLocaleDateString()}`
                  : ""}
              </span>
            </button>
            <button
              type="button"
              className={`session-delete${confirming === s.exploration_id ? " is-confirming" : ""}`}
              title={confirming === s.exploration_id
                ? `Click again to delete Session ${s.session_no}`
                : `Delete Session ${s.session_no}`}
              aria-label={confirming === s.exploration_id
                ? `Confirm delete Session ${s.session_no}`
                : `Delete Session ${s.session_no}`}
              disabled={deleting !== null}
              onClick={() => {
                if (confirming === s.exploration_id) {
                  setConfirming(null);
                  remove(s.exploration_id);
                } else {
                  setConfirming(s.exploration_id);
                }
              }}
            >
              {confirming === s.exploration_id
                ? <span className="session-delete-confirm">Delete?</span>
                : <Trash2 size={15} aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ul>
      {error && <div className="sessions-empty" role="alert">{error}</div>}
    </aside>
  );
}
