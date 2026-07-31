# Architecture

The unlimited research engine is a single, self-contained MCP server. Everything
lives under one process, one server name, and one tool surface — search,
scrape, deep-research, and diagnostics are not split across multiple MCP servers.

## Layout

```text
.
├── engine/
│   ├── mcp_research_server.py      # MCP entry point (stdio transport, 4 tools)
│   └── research/                   # engine package
│       ├── __init__.py             # public async API + diagnostics
│       ├── config.py               # env-driven configuration
│       ├── logging_utils.py        # stderr logger (keeps stdio channel clean)
│       ├── cache.py                # thread-safe TTL disk cache
│       ├── search.py               # SearXNG + DDGS, fusion, circuit breaker
│       ├── fetch.py                # cascading fetchers (HTTP → JS → PDF)
│       ├── extract.py              # trafilatura → markdownify → pypdf
│       └── report.py               # final report shaping
├── searxng/                        # local SearXNG container (search layer)
├── skill/SKILL.md                  # skill card (unlimited-research)
├── tests/                          # unit + live + MCP-protocol + stress tests
├── scripts/engine_status.py        # CLI health check
└── docs/
```

## Request flow

```
CLI/agent ──(MCP stdio)──▶ engine/mcp_research_server.py
                              │
                              ▼
                   research.deep_research(query)
                              │
             ┌────────────────┴─────────────────┐
             ▼                                  ▼
   search.search(query)               fetch_url(url) x N
   ├─ SearXNG (parallel)              ├─ disk cache hit?
   ├─ DuckDuckGo (parallel)           ├─ PDF?        → httpx + pypdf
   ├─ fuse + dedupe by URL            ├─ Scrapling   → stealthy HTTP fetch
   ├─ circuit breaker per source      └─ too empty?  → Crawl4AI/Playwright JS render
   └─ disk cache (10 min TTL)                        └─ retries + backoff + semaphore
                              │
                              ▼
                   report.build_report(...)  → JSON to CLI
```

## Search layer (`search.py`)

- All enabled sources are queried **in parallel** with `asyncio.gather`.
- Results are **deduplicated** with `canonical_url()` (lowercase host, drops
  tracking params/fragments/trailing slashes) and **interleaved by rank**
  (round-robin across the sources that responded).
- Each source has a **circuit breaker**: after N consecutive failures it is
  skipped for a cooldown window, so a flapping SearXNG container never blocks
  research — DDGS (or whatever remains) keeps serving results.
- Result sets are cached on disk for 10 minutes, so identical queries cost
  zero upstream requests.

## Fetch layer (`fetch.py`)

A single `fetch_url()` walks a cascade, escalating only when needed:

1. **Cache** — 6-hour TTL disk cache; repeat research never re-downloads.
2. **PDF fast path** — `.pdf` URLs are downloaded as bytes and parsed with
   pypdf (no browser involved).
3. **Scrapling fast path** — stealthy HTTP fetch with browser-like headers.
   Fast (~1–2 s) and sufficient for the large majority of sites.
4. **Browser escalation** — if the fast path returns no content or less than
   `FETCH_MIN_CONTENT` chars (JS-heavy SPA), the page is re-rendered with
   Crawl4AI/Playwright in a headless browser and extracted as clean markdown.
   The browser session is started lazily and **shared across every URL in one
   research run** (one browser launch for N pages).

Global safety rails: a shared `asyncio.Semaphore` (`RESEARCH_CONCURRENCY`, default 8),
per-fetch timeout, exponential-backoff retries, and optional proxy support
(`RESEARCH_PROXY`).

## Extraction (`extract.py`)

- **trafilatura** — best-in-class readability extraction, tables kept, clean
  markdown or plain text, plus metadata (title/author/site/language).
- **markdownify** — HTML→markdown fallback when trafilatura yields nothing.
- **pypdf** — PDF byte parsing for document links.

## Resilience & reliability

- Circuit breakers (per search source).
- Retry with exponential backoff on transient fetch failures.
- Concurrency semaphore prevents hammering any single host.
- Graceful degradation: a failed source or blocked page is reported per-result
  (`error` field) instead of aborting the whole research run.
- Blocked pages (403, Cloudflare, anti-bot) are *expected* upstream behavior,
  surfaced as `error` entries so the calling agent can decide what to do.

## Caching

| Cache | Key | TTL | Purpose |
|-------|-----|-----|---------|
| `SEARCH_CACHE` | query + num_results + time_range + sources | 10 min | no duplicate upstream searches |
| `FETCH_CACHE` | URL + format + max_len | 6 h | no duplicate page downloads |

Both are JSON files under `~/.cache/unlimited-research/` (override with
`RESEARCH_CACHE_DIR`) with a size cap (`RESEARCH_CACHE_ENTRIES`, default 5000).

## Configuration

Everything in `config.py` is overridable via environment variables:

| Env var | Default | Meaning |
|---------|---------|---------|
| `SEARXNG_URL` | `http://127.0.0.1:8081` | SearXNG instance |
| `SEARCH_SOURCES` | `searxng,ddgs` | fused sources, priority order |
| `RESEARCH_JS_RENDER` | `auto` | `auto` / `always` / `never` browser rendering |
| `RESEARCH_CRAWL4AI` | `true` | enable/disable the JS/browser tier |
| `RESEARCH_CONCURRENCY` | `8` | max parallel page fetches |
| `RESEARCH_CACHE_DIR` | `~/.cache/unlimited-research` | cache location |
| `SEARCH_CACHE_TTL` | `600` | search cache TTL seconds |
| `FETCH_CACHE_TTL` | `21600` | fetch cache TTL seconds |
| `RESEARCH_PROXY` | *(empty)* | optional proxy for all fetches |
| `FETCH_TIMEOUT` | `25` | per-request timeout seconds |
| `FETCH_RETRIES` | `2` | retry count with backoff |
