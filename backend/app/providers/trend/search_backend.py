"""The search seam.

`WebSearchTrendProvider` talks only to a SearchBackend. That is what lets the same
provider run against a keyed live search API, against a recorded corpus of genuinely
retrieved results, or against a deliberately failing stub in tests.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.providers.protocols import SearchError

RECORDED_ROOT = Path(__file__).parent / "recorded"


@dataclass(frozen=True)
class SearchResult:
    """One raw result. Deliberately dumb: extraction happens downstream."""
    title: str
    url: str
    snippet: str = ""
    published: date | None = None       # only when the backend actually reports one
    publisher: str = ""
    query: str = ""


# the contract lives in the domain; re-exported for callers of this module
__all__ = ["SearchResult", "SearchError", "SearchBackend", "HttpSearchBackend",
           "RecordedSearchBackend", "NullSearchBackend", "FailingSearchBackend"]


@runtime_checkable
class SearchBackend(Protocol):
    name: str
    is_live: bool

    def is_configured(self) -> bool: ...

    def search(self, query: str, *, limit: int = 8, region: str | None = None
               ) -> list[SearchResult]: ...


# ─────────────────────────── live ───────────────────────────

class HttpSearchBackend:
    """A keyed search API over plain HTTP.

    Shaped for the common `{"results": [{"title","url","description","page_age"}]}`
    response used by Brave/Tavily/Serper-style endpoints. NOT exercised in this
    environment — no key is configured — so it is written defensively and every failure
    surfaces as SearchError for the provider's per-domain handling.
    """
    name = "http"
    is_live = True

    def __init__(self, endpoint: str, api_key: str, *, timeout: float = 8.0,
                 retries: int = 1, header: str = "X-Subscription-Token") -> None:
        self.endpoint, self.api_key = endpoint, api_key
        self.timeout, self.retries, self.header = timeout, retries, header

    # provider name → (endpoint, auth header). Shapes only; none is exercised here.
    PROVIDERS: dict[str, tuple[str, str]] = {
        "brave": ("https://api.search.brave.com/res/v1/web/search", "X-Subscription-Token"),
        "tavily": ("https://api.tavily.com/search", "Authorization"),
        "serper": ("https://google.serper.dev/search", "X-API-KEY"),
    }

    @classmethod
    def for_provider(cls, provider: str, api_key: str, *, timeout: float = 8.0,
                     retries: int = 1) -> "HttpSearchBackend":
        endpoint, header = cls.PROVIDERS.get(provider.lower(), ("", "X-API-KEY"))
        backend = cls(endpoint, api_key, timeout=timeout, retries=retries, header=header)
        backend.name = f"http:{provider.lower()}" if endpoint else "http:unconfigured"
        return backend

    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key)

    def search(self, query: str, *, limit: int = 8, region: str | None = None
               ) -> list[SearchResult]:
        if not self.is_configured():
            raise SearchError(
                "search backend not configured: set SEARCH_BACKEND and SEARCH_API_KEY")
        params = {"q": query, "count": str(limit)}
        if region:
            params["country"] = region[:2].upper()
        url = f"{self.endpoint}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            self.header: self.api_key, "Accept": "application/json",
            "User-Agent": "csi-engine/0.1 (trend discovery)",
        })
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = json.loads(r.read().decode("utf-8", "replace"))
                return self._parse(payload, query)
            except Exception as exc:                       # noqa: BLE001 - all are retryable
                last = exc
                if attempt < self.retries:
                    time.sleep(0.4 * (attempt + 1))
        raise SearchError(f"search failed for {query!r}: {type(last).__name__}: {last}")

    @staticmethod
    def _parse(payload: dict, query: str) -> list[SearchResult]:
        rows = (payload.get("results")
                or payload.get("web", {}).get("results")
                or payload.get("organic")
                or [])
        out: list[SearchResult] = []
        for r in rows:
            url = r.get("url") or r.get("link") or ""
            if not url:
                continue
            out.append(SearchResult(
                title=(r.get("title") or "").strip(),
                url=url,
                snippet=(r.get("description") or r.get("snippet") or "").strip(),
                published=_parse_iso(r.get("page_age") or r.get("published_date")),
                publisher=(r.get("profile", {}) or {}).get("name", "") if isinstance(
                    r.get("profile"), dict) else "",
                query=query,
            ))
        return out


def _parse_iso(value) -> date | None:
    """Never guess. An unparseable value yields None."""
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:len(fmt) + 2].rstrip("Z"), fmt).date()
        except ValueError:
            continue
    return None


# ─────────────────────────── recorded ───────────────────────────

@dataclass
class RecordedSearchBackend:
    """Replays results that were genuinely retrieved from the web and captured to disk.

    This is what makes the live path testable and the benchmark honest: the evidence is
    real, only the transport is recorded. Unknown queries return [] rather than
    inventing a result.
    """
    name: str = "recorded"
    is_live: bool = False
    version: str = "v1"
    _corpus: dict[str, list[SearchResult]] = field(default_factory=dict)
    calls: int = 0

    def __post_init__(self) -> None:
        if self._corpus:
            return
        path = RECORDED_ROOT / f"{self.version}.json"
        if not path.exists():
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        for entry in raw["captures"]:
            self._corpus[_norm_q(entry["query"])] = [
                SearchResult(
                    title=r["title"], url=r["url"], snippet=r.get("snippet", ""),
                    published=_parse_iso(r.get("published")),
                    publisher=r.get("publisher", ""), query=entry["query"])
                for r in entry["results"]
            ]

    def is_configured(self) -> bool:
        return bool(self._corpus)

    def search(self, query: str, *, limit: int = 8, region: str | None = None
               ) -> list[SearchResult]:
        self.calls += 1
        key = _norm_q(query)
        if key in self._corpus:
            return self._corpus[key][:limit]
        # Fallback on SUBJECT tokens only. Every generated query shares "2026",
        # "design" and "trends", so matching on raw overlap served the retail capture
        # to a wedding query. A capture is only reused when the actual subject matches.
        q_tokens = set(key.split()) - GENERIC_QUERY_TOKENS
        if not q_tokens:
            return []
        best, best_score = None, 0.0
        for k, rows in self._corpus.items():
            k_tokens = set(k.split()) - GENERIC_QUERY_TOKENS
            if not k_tokens:
                continue
            score = len(q_tokens & k_tokens) / len(q_tokens | k_tokens)
            if score > best_score:
                best, best_score = rows, score
        return best[:limit] if best and best_score >= 0.5 else []


# Terms that appear in almost every generated query and therefore carry no subject.
GENERIC_QUERY_TOKENS = {
    "2024", "2025", "2026", "2027", "design", "designs", "trends", "trend", "current",
    "new", "latest", "the", "for", "and", "in", "of", "a", "luxury", "modern",
}


def _norm_q(q: str) -> str:
    return " ".join(sorted(q.lower().split()))


# ─────────────────────────── stubs ───────────────────────────

class NullSearchBackend:
    name = "null"
    is_live = False

    def is_configured(self) -> bool:
        return False

    def search(self, query: str, *, limit: int = 8, region: str | None = None):
        return []


class FailingSearchBackend:
    """Used by the failure-handling tests."""
    name = "failing"
    is_live = False

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on            # None => fail everything

    def is_configured(self) -> bool:
        return True

    def search(self, query: str, *, limit: int = 8, region: str | None = None):
        if self.fail_on is None or any(t in query.lower() for t in self.fail_on):
            raise SearchError(f"simulated failure for {query!r}")
        return []
