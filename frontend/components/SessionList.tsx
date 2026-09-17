"use client";
import { useCallback, useEffect, useState } from "react";
import { Session, isRunning, isStopped, listSessions } from "../lib/api";

/** Past runs, kept on disk by the backend so they outlive a restart.
 *  Numbered oldest-first, so Session 1 stays Session 1 as new runs arrive.
 *  Read-only on purpose: a row opens a run, nothing here can destroy one. */
export function SessionList({
  activeId,
  onOpen,
  refreshKey,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
  refreshKey: number;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [busy, setBusy] = useState(true);

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
          <li key={s.exploration_id}>
            <button
              className={`session-row${s.exploration_id === activeId ? " is-active" : ""}`}
              onClick={() => onOpen(s.exploration_id)}
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
          </li>
        ))}
      </ul>
    </aside>
  );
}
