"""Fetch layer — cascading page retrieval.

Leveled-up pipeline for fetching a single URL:

1. **Cache** — hit the TTL disk cache first; repeat research never re-downloads.
2. **PDF fast path** — ``.pdf`` links are downloaded as bytes and parsed with
   pypdf (no browser, no HTML parse).
3. **Scrapling fast path** — stealthy HTTP fetch with browser-like headers;
   fast, anti-bot friendly, works for the vast majority of pages.
4. **Browser escalation (Crawl4AI / Playwright)** — when the fast path returns
   nothing or too little content (JS-heavy SPA), the page is re-rendered in a
   real headless browser and extracted as clean markdown. The browser session
   is created lazily and shared across every URL in a research run, so N pages
   cost one browser launch.

Global safety rails: a shared concurrency semaphore, per-fetch timeout,
exponential-backoff retries, and optional proxy support.
"""

from __future__ import annotations

import asyncio
import os
import time
import urllib.parse
from typing import Any

import httpx

from .cache import FETCH_CACHE
from .config import (
    CRAWL4AI_ENABLED,
    DEFAULT_USER_AGENTS,
    FETCH_MIN_CONTENT,
    FETCH_RETRIES,
    FETCH_TIMEOUT,
    JS_RENDER,
    MAX_CONCURRENCY,
    PROXY,
    RETRY_BACKOFF,
)
from .extract import extract_content, extract_metadata, extract_pdf_text, truncate
from .logging_utils import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - import guard
    from scrapling.fetchers import Fetcher as ScraplingFetcher
    SCRAPLING_AVAILABLE = True
    SCRAPLING_ERROR = None
except Exception as exc:  # pragma: no cover
    ScraplingFetcher = None
    SCRAPLING_AVAILABLE = False
    SCRAPLING_ERROR = str(exc)

# Scrapling's Fetcher is built on curl_cffi; passing ``impersonate`` makes the
# fast path speak real-browser TLS/HTTP2 fingerprints (JA3/JA4), which is what
# defeats 403/bot walls that key on the client handshake.
_SCRAPLING_IMPERSONATE = os.getenv("SCRAPLING_IMPERSONATE", "chrome")

try:  # pragma: no cover - import guard
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    CRAWL4AI_AVAILABLE = True
    CRAWL4AI_ERROR = None
except Exception as exc:  # pragma: no cover
    AsyncWebCrawler = None
    BrowserConfig = None
    CrawlerRunConfig = None
    CacheMode = None
    CRAWL4AI_AVAILABLE = False
    CRAWL4AI_ERROR = str(exc)

_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENCY)


class CrawlerSession:
    """Lazily-started shared headless-browser session.

    The browser is only launched on first use (when a page actually needs JS
    rendering) and closed explicitly by the caller, so a research run that
    never hits a JS page never pays browser startup cost.
    """

    def __init__(self) -> None:
        self._crawler: Any | None = None
        self._lock = asyncio.Lock()
        self._started = 0.0

    @property
    def active(self) -> bool:
        return self._crawler is not None

    async def crawler(self) -> Any:
        async with self._lock:
            if self._crawler is None:
                if not CRAWL4AI_AVAILABLE:
                    raise RuntimeError(f"crawl4ai not available: {CRAWL4AI_ERROR}")
                config = BrowserConfig(
                    headless=True,
                    verbose=False,
                    enable_stealth=True,
                    user_agent=DEFAULT_USER_ACTIVE_UA(),
                )
                self._crawler = AsyncWebCrawler(config=config)
                await self._crawler.start()
                self._started = time.monotonic()
                logger.info("headless browser session started (stealth enabled)")
        return self._crawler

    async def close(self) -> None:
        async with self._lock:
            if self._crawler is not None:
                try:
                    await self._crawler.close()
                except Exception as exc:
                    logger.debug("browser close error: %s", exc)
                self._crawler = None
                logger.info("headless browser session closed")


def _js_enabled(force_js: bool) -> bool:
    if not (CRAWL4AI_AVAILABLE and CRAWL4AI_ENABLED):
        return False
    if JS_RENDER == "never":
        return False
    if JS_RENDER == "always":
        return True
    return True  # auto: escalate on empty/short content


def _looks_like_pdf(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    return path.endswith(".pdf") or ";.pdf" in path


def _fetch_key(url: str, fmt: str, max_len: int) -> str:
    return f"fetch|{url}|{fmt}|{max_len}"


async def fetch_url(
    url: str,
    fmt: str = "markdown",
    max_len: int = 8000,
    crawler_session: CrawlerSession | None = None,
    force_js: bool = False,
) -> dict[str, Any]:
    """Fetch a single URL through the cascade, with caching."""
    cached = FETCH_CACHE.get(_fetch_key(url, fmt, max_len))
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out

    result = await _fetch_cascade(url, fmt, max_len, crawler_session, force_js)
    result["cached"] = False
    if result.get("status") == 200 and result.get("content"):
        FETCH_CACHE.set(_fetch_key(url, fmt, max_len), result)
    return result


async def _fetch_cascade(
    url: str,
    fmt: str,
    max_len: int,
    crawler_session: CrawlerSession | None,
    force_js: bool,
) -> dict[str, Any]:
    async with _SEMAPHORE:
        try:
            if _looks_like_pdf(url):
                return await _cascade_pdf(url, fmt, max_len)

            page = await _fetch_scrapling(url)
            content = ""
            title = ""

            # Some PDFs are served without a .pdf URL (arXiv /pdf/xxxx paths).
            # Detect them by Content-Type at the fetch layer so they take the
            # fast pypdf route instead of crashing the browser tier.
            if page and page.get("status") == 200 and page.get("pdf_bytes"):
                text = extract_pdf_text(page["pdf_bytes"])
                if text:
                    return {
                        "url": url,
                        "status": 200,
                        "title": _pdf_title(url),
                        "content": truncate(text, max_len),
                        "content_length": min(len(text), max_len),
                        "method": "pdf",
                        "error": None,
                    }
                # Binary PDF with no extractable text: never send it to the
                # browser tier (Playwright aborts on "Download is starting").
                return {
                    "url": url,
                    "status": 200,
                    "title": _pdf_title(url),
                    "content": "",
                    "content_length": 0,
                    "method": "pdf",
                    "error": "pdf produced no extractable text",
                }

            if page and page.get("status") == 200:
                content = extract_content(page.get("html", ""), fmt, url)
                title = page.get("title", "")
                meta = extract_metadata(page.get("html", ""))
                title = title or meta.get("title", "")

            need_js = force_js or (len(content) < FETCH_MIN_CONTENT)
            if need_js and _js_enabled(force_js):
                js_result = await _crawl_js(url, fmt, crawler_session)
                if js_result.get("status") == 200 and len(js_result.get("content", "")) > len(content):
                    page = js_result
                    content = js_result.get("content", "")
                    title = title or js_result.get("title", "")

            if content:
                return {
                    "url": url,
                    "status": (page or {}).get("status", 200),
                    "title": title,
                    "content": truncate(content, max_len),
                    "content_length": min(len(content), max_len),
                    "method": (page or {}).get("method", "scrapling"),
                    "error": None,
                }
            return {
                "url": url,
                "status": (page or {}).get("status", 0),
                "title": title,
                "content": "",
                "content_length": 0,
                "method": (page or {}).get("method", "unknown"),
                "error": (page or {}).get("error") or "empty content",
            }
        except Exception as exc:
            return {"url": url, "status": 0, "title": "", "content": "", "content_length": 0, "method": "none", "error": str(exc)}


async def _cascade_pdf(url: str, fmt: str, max_len: int) -> dict[str, Any]:
    text, status, error = await _fetch_pdf(url)
    if text:
        return {
            "url": url,
            "status": status,
            "title": _pdf_title(url),
            "content": truncate(text, max_len),
            "content_length": min(len(text), max_len),
            "method": "pdf",
            "error": None,
        }
    return {"url": url, "status": status, "title": "", "content": "", "content_length": 0, "method": "pdf", "error": error or "pdf extraction failed"}


def _pdf_title(url: str) -> str:
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ") if name else url


async def _fetch_pdf(url: str) -> tuple[str, int, str | None]:
    headers = {"User-Agent": DEFAULT_USER_ACTIVE_UA()}
    for attempt in range(FETCH_RETRIES + 1):
        status = 0
        last_error: Exception | None = None

        # 1) HTTP/2 httpx attempt.
        try:
            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT,
                follow_redirects=True,
                proxy=PROXY or None,
                headers=headers,
                http2=True,
            ) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                text = extract_pdf_text(resp.content)
                if text:
                    return text, 200, None
                return "", 200, "pdf produced no extractable text"
            status = resp.status_code
        except Exception as exc:
            last_error = exc

        # 2) TLS-impersonated curl_cffi attempt for CDN-protected PDFs.
        try:
            def _run() -> tuple[int, bytes]:
                page = ScraplingFetcher.get(
                    url,
                    impersonate=_SCRAPLING_IMPERSONATE,
                    stealthy_headers=True,
                    follow_redirects=True,
                    timeout=FETCH_TIMEOUT,
                    proxy=PROXY or None,
                )
                return int(page.status), page.body or b""

            fstatus, body = await asyncio.to_thread(_run)
            if fstatus == 200 and body:
                text = extract_pdf_text(body)
                if text:
                    return text, 200, None
                return "", 200, "pdf produced no extractable text"
            if status == 0:
                status = fstatus
        except Exception as exc:
            last_error = exc

        if attempt < FETCH_RETRIES:
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
            continue
        if status:
            return "", status, f"http {status}"
        return "", 0, str(last_error) if last_error else "pdf fetch failed"

    return "", 0, "pdf fetch failed"


async def _fetch_scrapling(url: str) -> dict[str, Any] | None:
    if not SCRAPLING_AVAILABLE:
        logger.warning("scrapling unavailable: %s", SCRAPLING_ERROR)
        return None
    for attempt in range(FETCH_RETRIES + 1):
        try:
            def _run():
                try:
                    return ScraplingFetcher.get(
                        url,
                        impersonate=_SCRAPLING_IMPERSONATE,
                        stealthy_headers=True,
                        follow_redirects=True,
                        timeout=FETCH_TIMEOUT,
                        proxy=PROXY or None,
                    )
                except TypeError:
                    # Older scrapling without curl_cffi impersonation.
                    return ScraplingFetcher.get(
                        url,
                        stealthy_headers=True,
                        follow_redirects=True,
                        timeout=FETCH_TIMEOUT,
                        proxy=PROXY or None,
                    )

            page = await asyncio.to_thread(_run)
            title = ""
            content_type = ""
            try:
                content_type = (page.headers or {}).get("content-type", "")
            except Exception:
                pass
            if "pdf" in content_type.lower() or (page.body or b"").startswith(b"%PDF"):
                return {
                    "url": url,
                    "status": int(page.status),
                    "title": "",
                    "html": "",
                    "pdf_bytes": page.body or b"",
                    "method": "scrapling-pdf",
                    "error": None,
                }
            try:
                title_tag = page.find("title")
                if title_tag is not None:
                    title = title_tag.text.strip()
            except Exception:
                pass
            return {
                "url": url,
                "status": int(page.status),
                "title": title,
                "html": page.html_content or "",
                "method": "scrapling",
                "error": None,
            }
        except Exception as exc:
            if attempt >= FETCH_RETRIES:
                return {"url": url, "status": 0, "title": "", "html": "", "method": "scrapling", "error": str(exc)}
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
    return {"url": url, "status": 0, "title": "", "html": "", "method": "scrapling", "error": "scrapling fetch failed"}


async def _crawl_js(url: str, fmt: str, crawler_session: CrawlerSession | None) -> dict[str, Any]:
    if crawler_session is None:
        crawler_session = CrawlerSession()
        own_session = True
    else:
        own_session = False
    try:
        crawler = await crawler_session.crawler()
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            magic=True,
            max_retries=1,
            wait_until="load",
        )
        result = await crawler.arun(url, config=run_config)
        status = getattr(result, "status_code", 200)
        markdown = (
            getattr(result, "fit_markdown", None)
            or getattr(result, "raw_markdown", None)
            or getattr(result, "markdown", None)
            or ""
        )
        html = getattr(result, "html", "") or ""
        meta = getattr(result, "metadata", None) or {}
        content = markdown or extract_content(html, fmt, url)
        if not content:
            return {"url": url, "status": status, "title": "", "content": "", "content_length": 0, "method": "crawl4ai", "error": "js render returned no content"}
        return {
            "url": url,
            "status": status,
            "title": meta.get("title") or "",
            "content": content,
            "content_length": len(content),
            "method": "crawl4ai",
            "error": None,
        }
    except Exception as exc:
        return {"url": url, "status": 0, "title": "", "content": "", "content_length": 0, "method": "crawl4ai", "error": str(exc)}
    finally:
        if own_session:
            await crawler_session.close()


# ---------------------------------------------------------------------------
# User-agent rotation helpers
# ---------------------------------------------------------------------------
_ua_index = 0


def DEFAULT_USER_ACTIVE_UA() -> str:
    global _ua_index
    _ua_index = (_ua_index + 1) % len(DEFAULT_USER_AGENTS)
    return DEFAULT_USER_AGENTS[_ua_index]


# ---------------------------------------------------------------------------
# Backward-compatible aliases used by the original stress test / callers.
# ---------------------------------------------------------------------------
async def _scrape_with_scrapling(url: str, fmt: str, max_len: int) -> dict[str, Any]:
    return await fetch_url(url, fmt, max_len)
