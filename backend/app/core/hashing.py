"""Canonical serialisation + hashing, so identical inputs hash identically
on any machine (spec R-PC-01)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return canonical(obj.model_dump(mode="json"))
    if isinstance(obj, dict):
        return {k: canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [canonical(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(canonical(obj), separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def short_hash(obj: Any, n: int = 12) -> str:
    return sha256_of(obj)[:n]
