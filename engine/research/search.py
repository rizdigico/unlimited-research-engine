"""Search layer.

Strategy (leveled up from the original single-source flow):

1. Query every enabled source in parallel — local SearXNG meta-search first,
   DuckDuckGo (``ddgs``) second, with graceful per-source failure.
2. Fuse the result lists: dedupe by canonicalized URL, then interleave by rank
   so the top results from *all* working sources surface early.
3. A per-source circuit breaker means one flaky source (e.g. SearXNG being
   restarted) never takes down research; the remaining sources keep working.
4. Full result sets are cached on disk for a TTL window so repeated queries do
   not re-hit upstream engines at all.

No external API keys are used anywhere in this file.
"""

from __future__ import annotations

import asyncio
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx

from .cache import SEARCH_CACHE
from .config import (
    CIRCUIT_COOLDOWN,
    CIRCUIT_FAIL_THRESHOLD,
    DDGS_MAX_RESULTS,
    DDGS_TIMEOUT,
    SEARCH_SOURCES,
    SEARXNG_TIMEOUT,
    SEARXNG_URL,
    TIME_RANGE_MAP,
)
from .logging_utils import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - import guard
    from ddgs import DDGS
    DDGS_AVAILABLE = True
    DDGS_ERROR = None
except Exception as exc:  # pragma: no cover
    DDGS = None
    DDGS_AVAILABLE = False
    DDGS_ERROR = str(exc)

_CIRCUIT_SENTINEL = object()


@dataclass
class CircuitBreaker:
    """Opens after ``fail_threshold`` consecutive failures, then re-arms after
    ``cooldown`` seconds of silence so a recovered upstream gets retried."""

    name: str
    fail_threshold: int = CIRCUIT_FAIL_THRESHOLD
    cooldown: float = CIRCUIT_COOLDOWN
    _consecutive_failures: int = field(default=0, init=False)
    _open_until: float = field(default=0.0, init=False)

    def allow(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.fail_threshold:
            self._open_until = time.monotonic() + self.cooldown
            logger.warning(
                "%s circuit opened after %d failures; cooling down %.0fs",
                self.name,
                self._consecutive_failures,
                self.cooldown,
            )


SEARXNG_BREAKER = CircuitBreaker("searxng")


def canonical_url(url: str) -> str:
    """Lowercase host, drop fragment, drop tracking params, collapse trailing
    slash — used to dedupe near-identical URLs from different engines."""
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception:
        return url.strip().lower()
    host = (parsed.netloc or "").lower()
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    if query:
        keep = []
        for pair in query.split("&"):
            k = pair.split("=", 1)[0].lower()
            if k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "ref_src"):
                continue
            keep.append(pair)
        query = "&".join(keep)
    rebuilt = urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, query, ""))
    return rebuilt


def _normalize_searxng_results(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert SearXNG result objects to the shared result shape."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "title": item.get("title", "").strip(),
                "href": url,
                "body": item.get("content", "").strip(),
                "engines": item.get("engines", []),
                "score": item.get("score", 0),
                "publishedDate": item.get("publishedDate"),
                "source": "searxng",
            }
        )
    return out


async def search_searxng(query: str, num_results: int, time_range: str = "") -> list[dict[str, Any]]:
    params: dict[str, Any] = {"format": "json", "q": query}
    if time_range:
        params["time_range"] = TIME_RANGE_MAP.get(time_range, time_range)

    async with httpx.AsyncClient(timeout=SEARXNG_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(f"{SEARXNG_URL}/search", params=params)
        resp.raise_for_status()
        data = resp.json()
        return _normalize_searxng_results(data.get("results", []))[:num_results]


async def search_ddgs(query: str, num_results: int, time_range: str = "") -> list[dict[str, Any]]:
    if not DDGS_AVAILABLE:
        raise RuntimeError(f"ddgs not available: {DDGS_ERROR}")

    def _run() -> list[dict[str, Any]]:
        with DDGS(timeout=DDGS_TIMEOUT) as ddgs:
            raw = list(ddgs.text(query, max_results=max(DDGS_MAX_RESULTS, num_results), timelimit=time_range or None))
        out: list[dict[str, Any]] = []
        for item in raw:
            href = (item.get("href") or item.get("url") or "").strip()
            if not href:
                continue
            out.append(
                {
                    "title": (item.get("title") or "").strip(),
                    "href": href,
                    "body": (item.get("body") or "").strip(),
                    "engines": ["duckduckgo"],
                    "score": 1.0,
                    "publishedDate": item.get("date"),
                    "source": "ddgs",
                }
            )
        return out[:num_results]

    return await asyncio.to_thread(_run)


async def _search_single(
    source: str, query: str, num_results: int, time_range: str
) -> tuple[str, list[dict[str, Any]] | object]:
    """Run one source with its circuit breaker. Returns (source, results|SENTINEL)."""
    breaker = SEARXNG_BREAKER if source == "searxng" else CircuitBreaker(source)
    if not breaker.allow():
        logger.info("circuit open, skipping source=%s", source)
        return source, _CIRCUIT_SENTINEL
    try:
        if source == "searxng":
            results = await search_searxng(query, num_results, time_range)
        elif source == "ddgs":
            results = await search_ddgs(query, num_results, time_range)
        else:
            return source, []
        breaker.record_success()
        return source, results
    except Exception as exc:
        breaker.record_failure()
        logger.warning("search source=%s failed: %s", source, exc)
        return source, exc


def _fuse(results_by_source: dict[str, list[dict[str, Any]]], num_results: int) -> list[dict[str, Any]]:
    """Dedupe across sources and interleave by rank (round-robin over the
    sources that returned results, highest-priority source first)."""
    order = [s for s in SEARCH_SOURCES if s in results_by_source]
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    max_rank = max((len(results_by_source[s]) for s in order), default=0)

    for rank in range(max_rank):
        for source in order:
            items = results_by_source[source]
            if rank >= len(items):
                continue
            item = items[rank]
            key = canonical_url(item["href"])
            if key in seen:
                continue
            seen.add(key)
            out = dict(item)
            out["rank"] = len(merged) + 1
            merged.append(out)
            if len(merged) >= num_results:
                return merged
    return merged[:num_results]


async def search(
    query: str, num_results: int = 10, time_range: str = "", sources: tuple[str, ...] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fused search across all enabled sources.

    Returns ``(results, sources_used)`` where ``sources_used`` lists every
    source that contributed at least one result (empty if nothing worked).
    """
    sources = sources or SEARCH_SOURCES
    cache_key = f"search|{query}|{num_results}|{time_range}|{','.join(sources)}"
    cached = SEARCH_CACHE.get(cache_key)
    if cached is not None:
        return cached["results"], cached["sources_used"]

    tasks = [_search_single(s, query, num_results, time_range) for s in sources]
    raw = await asyncio.gather(*tasks)

    results_by_source: dict[str, list[dict[str, Any]]] = {}
    failures: list[str] = []
    for source, outcome in raw:
        if outcome is _CIRCUIT_SENTINEL:
            failures.append(source)
            continue
        if isinstance(outcome, Exception):
            failures.append(source)
            continue
        results_by_source[source] = outcome

    merged = _fuse(results_by_source, num_results)
    sources_used = list(results_by_source.keys())
    if not merged and failures:
        raise RuntimeError(f"all search sources failed: {', '.join(failures)}")

    SEARCH_CACHE.set(cache_key, {"results": merged, "sources_used": sources_used})
    return merged, sources_used


# ---------------------------------------------------------------------------
# Backward-compatible aliases used by the original stress test / callers.
# ---------------------------------------------------------------------------
async def _search(query: str, num_results: int, time_range: str) -> tuple[list[dict[str, Any]], str]:
    results, sources_used = await search(query, num_results, time_range)
    return results, sources_used[0] if sources_used else "none"
