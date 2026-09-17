"""Engine logging.

The pipeline already records a StageRun for every stage, which answers "what
happened?" *after* a run finishes. This adds the other half: a live trace you can
watch while it runs, and — the part that actually saves debugging time — an
explicit line for every stage that DID NOT run and why.

A silent absence is the hardest thing to debug. "no cognition stage in the trace"
looks identical whether the layer is disabled, the provider is unconfigured, or a
branch was never reached. `skip()` makes those three different lines.

Format is fixed-width so a run reads as a column:

    12:04:41  INFO   engine     05 Niche allocation      OK      129ms  10 niches: CANO/EXPL/...
    12:04:41  INFO   engine     08c Creative cognition   SKIP           disabled (CREATIVE_COGNITION_ENABLED=false)
    12:07:02  WARN   engine     concept cn_1a2b rejected  GATE_FAILED  FEAS_SPAN_EXCEEDED

Level is set by ENGINE_LOG_LEVEL (default INFO). DEBUG adds per-concept detail.
"""
from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "engine"
_CONFIGURED = False


class _Formatter(logging.Formatter):
    """Aligned columns, no ANSI. Terminals, log files and CI all render this the same."""

    LEVEL = {"DEBUG": "DEBUG", "INFO": "INFO ", "WARNING": "WARN ",
             "ERROR": "ERROR", "CRITICAL": "FATAL"}

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        lvl = self.LEVEL.get(record.levelname, record.levelname[:5])
        return f"{ts}  {lvl}  {record.name:<10} {record.getMessage()}"


def setup(level: str | None = None) -> None:
    """Idempotent. Safe to call from create_app() and from a test."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    lvl = (level or os.environ.get("ENGINE_LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter())
    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(getattr(logging, lvl, logging.INFO))
    log.handlers[:] = [handler]
    log.propagate = False          # uvicorn owns the root logger; do not duplicate
    _CONFIGURED = True


def get(name: str = "") -> logging.Logger:
    setup()
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


# ── the vocabulary the pipeline logs in ─────────────────────────────────────
# Deliberately small. Every line is one of these shapes, so a run is scannable
# and a grep for "SKIP" or "REJECT" answers a whole class of question at once.

def stage(code: str, label: str, status: str, ms: int, detail: str = "",
          calls: int = 0) -> None:
    """One completed stage."""
    log = get()
    line = f"{code:<4} {label:<24} {status:<7} {ms:>6}ms  {detail}"
    if calls:
        line += f"   [{calls} llm]"
    (log.error if status == "FAILED" else log.info)(line)


def skip(code: str, label: str, reason: str) -> None:
    """A stage that did NOT run, and why. This is the line that saves an hour."""
    get().info(f"{code:<4} {label:<24} SKIP           {reason}")


def note(msg: str) -> None:
    get().info(msg)


def detail(msg: str) -> None:
    """Per-concept noise. Hidden unless ENGINE_LOG_LEVEL=DEBUG."""
    get().debug(f"     {msg}")


def prompt(index: int, title: str, sections: list, prompt_hash: str,
           full: str = "") -> None:
    """One concept's image prompt, printed where you can read it.

    At INFO the sections that decide what the image LOOKS like — subject, palette,
    style, camera. At DEBUG the whole compiled prompt, because when a render is
    wrong the answer is almost always a section you did not expect to be there.
    """
    log = get()
    log.info("")
    log.info(f"  [{index:02d}] {title}")
    for name in ("SUBJECT", "PALETTE", "LIGHTING", "MATERIALS",
                 "ARCHITECTURAL VISUALIZATION STYLE", "CAMERA"):
        text = next((t for n, t in sections if n == name), "")
        if text:
            log.info(f"       {name:<34} {text[:118]}")
    log.info(f"       {'hash':<34} {prompt_hash[:16]}")
    if full:
        log.debug("       " + "-" * 60)
        for line in full.splitlines():
            log.debug(f"       {line}")


def warn(msg: str) -> None:
    get().warning(msg)


def error(msg: str) -> None:
    get().error(msg)
