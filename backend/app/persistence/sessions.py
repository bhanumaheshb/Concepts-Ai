"""Session archive — past runs that survive a restart.

The engine's store is in-memory by design: it holds live ExplorationRecords for the
pipeline, and losing them on restart costs nothing because a run is reproducible
from its seed. What it DOES cost is the user's history — every previous exploration
vanishes with the process.

So this saves the SERIALISED API PAYLOAD rather than the internal record. That
choice matters: the payload is plain JSON, human-readable, and survives changes to
the domain models underneath it. Pickling ExplorationRecord would be less code and
would break the first time a Pydantic field moved.

Read-only history. Nothing here feeds back into the engine.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# SESSIONS_DIR relocates the archive. The test suite points it at a temporary
# directory: a user's history is real data and a test run must never write into it.
ROOT = Path(__file__).resolve().parents[2] / ".sessions"


def _root() -> Path:
    override = os.environ.get("SESSIONS_DIR")
    return Path(override) if override else ROOT


class SessionArchive:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else _root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, exploration_id: str) -> Path:
        # ids are engine-generated (ex_<hex>); reject anything else rather than
        # letting a crafted id walk out of the archive directory
        safe = "".join(ch for ch in exploration_id if ch.isalnum() or ch in "_-")
        return self.root / f"{safe}.json"

    # ---- writing -----------------------------------------------------------
    def save(self, exploration_id: str, payload: dict[str, Any],
             concepts: dict[str, dict[str, Any]] | None = None) -> None:
        """Write (or overwrite) a run's history entry.

        Called repeatedly while a run is in flight and once more when it ends, so
        the history shows a run from its first concept rather than only after the
        last one. The write is atomic, so a reader never sees a half-written file.
        """
        doc = {
            "saved_at": time.time(),
            "exploration": payload,
            "concepts": concepts or {},
        }
        tmp = self._path(exploration_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(exploration_id))     # atomic: no half-written session

    # ---- reading -----------------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        """Newest first, with a 1-based session number the UI can show."""
        rows: list[dict[str, Any]] = []
        for f in self.root.glob("ex_*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue                              # a corrupt file hides itself
            ex = doc.get("exploration", {})
            brief = ex.get("brief") or {}
            concepts = ex.get("concepts") or []
            # A concept is written once the writer has produced its prose. Counting
            # them is what lets the sidebar say "3 of 10" while a run is still going.
            written = sum(1 for x in concepts
                          if (x.get("synthesis") or {}).get("available") is True)
            rows.append({
                "exploration_id": ex.get("exploration_id", f.stem),
                "saved_at": doc.get("saved_at", 0.0),
                "started_at": ex.get("started_at") or doc.get("saved_at", 0.0),
                "status": ex.get("status", "UNKNOWN"),
                "brief": (brief.get("raw_text") or brief.get("text") or "")[:120],
                "concepts": len(concepts),
                "written": written,
                "seed": ex.get("seed"),
                "k": ex.get("k"),
            })
        # Ordered by when the run STARTED, not when it was last snapshotted — a run
        # in progress rewrites its file every few seconds and would otherwise keep
        # jumping to the top and renumbering everything below it.
        rows.sort(key=lambda r: r["started_at"], reverse=True)
        total = len(rows)
        for i, r in enumerate(rows):
            r["session_no"] = total - i          # oldest is Session 1
        return rows

    def get(self, exploration_id: str) -> dict[str, Any] | None:
        f = self._path(exploration_id)
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None

    def delete(self, exploration_id: str) -> bool:
        f = self._path(exploration_id)
        if f.exists():
            f.unlink()
            return True
        return False
