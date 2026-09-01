"""Evidence extraction, normalisation, syndication collapse and entity resolution.

Web content is treated as DATA. Nothing retrieved is ever placed in an instruction
position; injection markers are stripped and recorded, never obeyed.
"""
from __future__ import annotations

import difflib
import re
import urllib.parse
from datetime import date, datetime, timezone

from app.domain.trend import (
    EvidenceType, SourceTier, TrendEvidence, TIER_SCORE,
)
from app.providers.trend.search_backend import SearchResult
from app.trends.scoring import tier_for

# ── security: retrieved text is data ────────────────────────────────────────
INJECTION_MARKERS = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions|disregard (the )?(system|previous)"
    r"|you are now|new instructions?:|system prompt|<\|.*?\|>)", re.I)

# ── source policy ───────────────────────────────────────────────────────────
# Content farms and obvious SEO/AI-generated hosts. Never auto-rejected — demoted, so
# they can corroborate but can never be a candidate's only evidence.
CONTENT_FARM_HINTS = ("aispaces", "gpt", "-ai.", "seo", "articlefarm", "contenthub")
# Vendor blogs writing about their own category: real, but self-interested.
VENDOR_HINTS = ("displays", "shop", "store", "supply", "construction", "recruiters",
                "foodservice", "group.com", "consulting", "venues")
STOPWORDS = {"the", "a", "an", "and", "or", "of", "for", "in", "on", "to", "with",
             "that", "how", "what", "we", "your", "you", "are", "is", "will", "top",
             "best", "trends", "trend", "2025", "2026", "2027", "guide", "watch"}


def strip_injection(text: str) -> tuple[str, bool]:
    """Returns (clean text, whether an injection marker was present)."""
    if not text:
        return "", False
    found = bool(INJECTION_MARKERS.search(text))
    return (INJECTION_MARKERS.sub(" ", text).strip() if found else text.strip()), found


def registrable_host(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return ""
    host = host.split(":")[0].removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 and len(parts[-2]) > 3 else host


def canonicalise(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return url
    query = urllib.parse.urlencode(
        [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))])
    return urllib.parse.urlunparse(
        (p.scheme or "https", p.netloc.lower().removeprefix("www."),
         p.path.rstrip("/"), "", query, ""))


def normalise_title(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(w for w in words if w not in STOPWORDS)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def date_from_url(url: str) -> date | None:
    """A date encoded in the path is verifiable. Anything else is not guessed."""
    m = re.search(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(/|$)", url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def classify_tier(url: str, publisher: str) -> SourceTier:
    """Existing tier map, then the deny/vendor policy on top."""
    host = registrable_host(url)
    tier = tier_for(f"{host} {publisher}")
    if any(h in host for h in CONTENT_FARM_HINTS):
        return SourceTier.SOCIAL                 # weakest corroboration, never sole
    if tier in (SourceTier.AGGREGATOR,) and any(h in host for h in VENDOR_HINTS):
        return SourceTier.COMMUNITY
    return tier


def to_evidence(result: SearchResult, *, now: datetime | None = None
                ) -> tuple[TrendEvidence, bool]:
    """SearchResult → TrendEvidence. Returns (evidence, injection_detected)."""
    now = now or datetime.now(timezone.utc)
    excerpt, flagged_a = strip_injection(result.snippet)
    title, flagged_b = strip_injection(result.title)
    host = registrable_host(result.url)
    publisher = result.publisher or host
    published = result.published or date_from_url(result.url)   # never fabricated
    return TrendEvidence(
        source=publisher or host,
        source_tier=classify_tier(result.url, publisher),
        url=result.url,
        published=published,
        excerpt=excerpt[:400],
        is_mock=False,
        title=title[:200],
        publisher=publisher,
        canonical_url=canonicalise(result.url),
        retrieved_at=now,
        evidence_type=EvidenceType.SEARCH_RESULT,
        query=result.query,
    ), (flagged_a or flagged_b)


# ── deduplication and syndication ───────────────────────────────────────────

TITLE_SAME = 0.85
TITLE_NEAR = 0.70
EXCERPT_NEAR = 0.70


def collapse_syndication(items: list[TrendEvidence]) -> tuple[list[TrendEvidence], list[str]]:
    """Collapse duplicates and syndicated copies into one signal each.

    A syndicated copy on another host is NOT an independent source: counting it as one
    is exactly how a single article becomes a fake 'trend'.
    """
    kept: list[TrendEvidence] = []
    notes: list[str] = []
    for item in items:
        dup_of = None
        for k in kept:
            if item.canonical_url and item.canonical_url == k.canonical_url:
                dup_of = k
                break
            t = similarity(normalise_title(item.title), normalise_title(k.title))
            if t >= TITLE_SAME:
                dup_of = k
                break
            if (t >= TITLE_NEAR
                    and similarity(item.excerpt.lower(), k.excerpt.lower()) >= EXCERPT_NEAR
                    and registrable_host(item.url or "") != registrable_host(k.url or "")):
                dup_of = k
                break
        if dup_of is None:
            kept.append(item)
            continue
        # A duplicate on a DIFFERENT host is a syndicated copy however it was matched.
        # Recording it only on the near-title branch under-reported syndication whenever
        # the copy kept the original headline — which is the common case.
        here, there = registrable_host(item.url or ""), registrable_host(dup_of.url or "")
        if here and there and here != there:
            notes.append(f"syndication: {here} ← {there}")
    return kept, notes


def independent_sources(items: list[TrendEvidence]) -> int:
    """Distinct registrable hosts AFTER collapsing. Different pages on one publisher
    are one source."""
    return len({registrable_host(e.url or "") or e.source.lower() for e in items})


# ── entity resolution ───────────────────────────────────────────────────────

CLAIM_NOISE = re.compile(
    r"^\s*(top\s+\d+|\d+)\s+|(\b(trends?|predictions?|guide|playbook|ideas?|watch|"
    r"forecast|roundup)\b)|\b(for|in|of)\s+20\d{2}\b|\b20\d{2}\b|[:\|].*$", re.I)


def resolve_entity(titles: list[str], domain_phrase: str) -> str:
    """An article headline is not a reference identity.

    'Top Experiential Design Trends Shaping Events in 2026' → 'experiential event design'.
    Raw headlines never reach the creative engine.
    """
    cleaned: list[str] = []
    for t in titles:
        c = CLAIM_NOISE.sub(" ", t)
        c = re.sub(r"\b(shaping|influencing|elevate|creating|designing|redefining|"
                   r"returns?|embrace|beyond|inside|how|what|why)\b", " ", c, flags=re.I)
        c = re.sub(r"[^A-Za-z\- ]+", " ", c)
        c = " ".join(w for w in c.split() if w.lower() not in STOPWORDS)
        if c:
            cleaned.append(c.strip().lower())
    if not cleaned:
        return domain_phrase
    # the most common meaningful bigram across the surviving titles
    counts: dict[str, int] = {}
    for c in cleaned:
        words = c.split()
        for i in range(len(words) - 1):
            counts[" ".join(words[i:i + 2])] = counts.get(" ".join(words[i:i + 2]), 0) + 1
    if counts:
        best = max(counts.items(), key=lambda kv: (kv[1], -len(kv[0])))
        if best[1] >= 2:
            return best[0]
    return cleaned[0][:60] or domain_phrase
