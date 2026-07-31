"""Runtime configuration for the unlimited research engine.

Every setting can be overridden with an environment variable so the exact same
code runs on a laptop, a desktop, or a VPS. Nothing here requires an API key.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Search layer
# ---------------------------------------------------------------------------
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8081")
SEARXNG_TIMEOUT = float(os.getenv("SEARXNG_TIMEOUT", "25"))

DDGS_TIMEOUT = float(os.getenv("DDGS_TIMEOUT", "20"))
DDGS_MAX_RESULTS = int(os.getenv("DDGS_MAX_RESULTS", "30"))

# Which search sources participate in fusion, in priority order.
SEARCH_SOURCES = tuple(
    s.strip()
    for s in os.getenv("SEARCH_SOURCES", "searxng,ddgs").split(",")
    if s.strip()
)

# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
CACHE_DIR = Path(os.getenv("RESEARCH_CACHE_DIR", str(Path.home() / ".cache" / "unlimited-research")))
SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "600"))  # seconds (10 min)
FETCH_CACHE_TTL = int(os.getenv("FETCH_CACHE_TTL", "21600"))  # seconds (6 h)
MAX_CACHE_ENTRIES = int(os.getenv("RESEARCH_CACHE_ENTRIES", "5000"))

# ---------------------------------------------------------------------------
# Fetch / scrape layer
# ---------------------------------------------------------------------------
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "25"))
FETCH_RETRIES = int(os.getenv("FETCH_RETRIES", "2"))
RETRY_BACKOFF = float(os.getenv("FETCH_RETRY_BACKOFF", "1.5"))
MAX_CONCURRENCY = int(os.getenv("RESEARCH_CONCURRENCY", "8"))

# Below this many chars of extracted content the fast path is considered a
# miss and the page is re-rendered with a real browser (when JS rendering is on).
FETCH_MIN_CONTENT = int(os.getenv("FETCH_MIN_CONTENT", "200"))

# auto  -> use the browser only when the fast path fails or returns nothing
# always-> always render with the browser first
# never -> never launch a browser
JS_RENDER = os.getenv("RESEARCH_JS_RENDER", "auto").strip().lower()
CRAWL4AI_ENABLED = os.getenv("RESEARCH_CRAWL4AI", "true").strip().lower() in ("1", "true", "yes")

# Optional proxy for all outbound fetches, e.g. http://user:pass@host:port
PROXY = os.getenv("RESEARCH_PROXY", "")

# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------
CIRCUIT_FAIL_THRESHOLD = int(os.getenv("CIRCUIT_FAIL_THRESHOLD", "2"))
CIRCUIT_COOLDOWN = float(os.getenv("CIRCUIT_COOLDOWN", "60"))

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
TIME_RANGE_MAP = {"d": "day", "w": "week", "m": "month", "y": "year"}

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]
