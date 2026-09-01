"""Everything needed to answer 'why did the system produce this concept?' and
'why did it reject that one?' from stored data alone (spec §24)."""
from __future__ import annotations

from app.domain.common import Frozen


class StageRun(Frozen):
    stage: str
    label: str
    status: str = "OK"          # OK | SKIPPED | FAILED
    attempt: int = 1
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    cache_hit: bool = False
    latency_ms: int = 0
    detail: str = ""


class RepairRecord(Frozen):
    concept_id: str
    attempt: int
    finding_code: str
    operator: str
    outcome: str
    before_summary: str = ""
    after_summary: str = ""
    detail: str = ""


class RejectionRecordTrace(Frozen):
    concept_id: str
    stage: str
    reason_code: str
    detail: str = ""
