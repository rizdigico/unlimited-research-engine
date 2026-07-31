"""unlimited-research — public API of the research engine.

All search, scrape, and report orchestration lives behind these few async
functions so both the MCP server and the test suite share one code path.
"""

from __future__ import annotations

from typing import Any

from .cache import FETCH_CACHE, SEARCH_CACHE
from .config import JS_RENDER, SEARXNG_URL
from .fetch import CrawlerSession, fetch_url
from .report import build_report
from .search import search

__all__ = [
    "deep_research",
    "search",
    "search_urls",
    "scrape_url",
    "engine_status",
    "CrawlerSession",
    "fetch_url",
]

DEFAULT_NUM_RESULTS = 5
DEFAULT_MAX_LENGTH = 8000
MAX_NUM_RESULTS = 15
MAX_CONTENT_LENGTH = 50000


async def search_urls(query: str, num_results: int = 10, time_range: str = "") -> dict[str, Any]:
    """Search only — return fused, deduped URL lists from all working sources."""
    results, sources_used = await search(query, num_results, time_range)
    return {"query": query, "sources_used": sources_used, "results": results}


async def scrape_url(
    url: str,
    fmt: str = "markdown",
    max_content_length: int = DEFAULT_MAX_LENGTH,
    js_render: str | None = None,
) -> dict[str, Any]:
    """Scrape a single URL through the full cascade."""
    session = CrawlerSession()
    try:
        force_js = js_render is not None and js_render.strip().lower() == "always"
        result = await fetch_url(url, fmt, max_content_length, crawler_session=session, force_js=force_js)
        result.pop("cached", None)
        return result
    finally:
        await session.close()


async def deep_research(
    query: str,
    num_results: int = DEFAULT_NUM_RESULTS,
    max_content_length: int = DEFAULT_MAX_LENGTH,
    time_range: str = "",
    js_render: str | None = None,
) -> dict[str, Any]:
    """Search + deep-scrape the top N results in one pass, sharing a single
    browser session across all fetches."""
    urls, sources_used = await search(query, num_results, time_range)
    force_js = js_render is not None and js_render.strip().lower() == "always"

    import asyncio

    session = CrawlerSession()
    try:
        tasks = [fetch_url(u["href"], "markdown", max_content_length, crawler_session=session, force_js=force_js) for u in urls]
        scraped = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await session.close()

    return build_report(query, urls, scraped, sources_used)


async def engine_status() -> dict[str, Any]:
    """Diagnostics: every dependency's availability plus cache stats and live
    SearXNG reachability. Used by the ``engine_status`` MCP tool."""
    import importlib.metadata as meta
    import sys

    def _pkg_version(name: str) -> str:
        try:
            return meta.version(name)
        except Exception:
            return "?"

    # Live SearXNG ping
    searxng_ok = False
    searxng_error = None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SEARXNG_URL}/search", params={"format": "json", "q": "ping"})
            searxng_ok = resp.status_code == 200
            if not searxng_ok:
                searxng_error = f"http {resp.status_code}"
    except Exception as exc:
        searxng_error = str(exc)

    from . import fetch as _fetch
    from . import extract as _extract

    import importlib

    _search = importlib.import_module(f"{__name__}.search")

    return {
        "python": sys.version.split()[0],
        "engine": "unlimited-research",
        "dependencies": {
            "httpx": _pkg_version("httpx"),
            "scrapling": _pkg_version("scrapling"),
            "crawl4ai": _pkg_version("crawl4ai"),
            "trafilatura": _pkg_version("trafilatura"),
            "markdownify": _pkg_version("markdownify"),
            "pypdf": _pkg_version("pypdf"),
            "ddgs": _pkg_version("ddgs"),
            "mcp": _pkg_version("mcp"),
        },
        "availability": {
            "scrapling": _fetch.SCRAPLING_AVAILABLE,
            "crawl4ai": _fetch.CRAWL4AI_AVAILABLE,
            "trafilatura": _extract.TRAFILATURA_AVAILABLE,
            "markdownify": _extract.MARKDOWNIFY_AVAILABLE,
            "pypdf": _extract.PYPDF_AVAILABLE,
            "ddgs": _search.DDGS_AVAILABLE,
        },
        "config": {
            "searxng_url": SEARXNG_URL,
            "searxng_reachable": searxng_ok,
            "searxng_error": searxng_error,
            "js_render": JS_RENDER,
            "search_sources": list(_search.SEARCH_SOURCES),
        },
        "cache": {
            "search": SEARCH_CACHE.stats(),
            "fetch": FETCH_CACHE.stats(),
        },
    }
