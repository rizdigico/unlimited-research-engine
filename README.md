# Unlimited No-API Web Research Engine

A self-hosted, **no-API-key, rate-limit-resistant, bot-detection-resistant**
deep research stack exposed as **one** MCP server (`unlimited-research`). Built
for agents that need unlimited web research: search across many engines at
once, then deep-scrape the best results — HTML, JavaScript-heavy SPAs, and PDFs.

- **Search** — local **SearXNG** meta-search + **DuckDuckGo**, queried in
  parallel, paginated up to 10 pages per query, fused, deduplicated by
  canonical URL, and interleaved by rank. Up to **200 results** per query with
  no artificial cap. DDG backends rotate with a politeness interval so bursts
  never trip anti-abuse.
- **Scrape** — cascading fetchers: **Scrapling/curl_cffi** (real-browser TLS
  fingerprint impersonation) → **Crawl4AI / Playwright** (stealth browser with
  magic mode + anti-bot retries for JS-heavy/Cloudflare pages) → **pypdf**
  (PDFs, including extensionless `/pdf/` URLs detected by Content-Type), with
  retries, backoff, concurrency limits, and optional proxy support.
- **Extract** — **trafilatura** readability extraction (tables kept, metadata
  included) with **markdownify** fallback.
- **Diagnostics** — a built-in `engine_status` tool reports dependency health,
  live SearXNG reachability, config, and cache stats.

> No paid API keys. No external AI models. No client-side search-engine rate limits.

---

## Why this exists

Most "deep research" tools depend on paid APIs (OpenAI, Google, Bing,
Perplexity) and hit rate limits or cost walls quickly. This engine removes all
of that:

1. A local **SearXNG** container fans every query across many free upstream
   search engines (Google, Bing, DuckDuckGo, Brave, Startpage, Qwant, Mojeek,
   Yahoo, Presearch, Marginalia, Wikipedia, Crossref, PubMed, Google Scholar...).
2. **DuckDuckGo** runs in parallel as a second independent source (with backend
   rotation), so a flapping SearXNG never stops research.
3. The best URLs are **deep-scraped** with a three-tier cascade that handles
   static HTML, JS-heavy SPAs, and PDFs — using browser-grade TLS/HTTP2
   fingerprints and stealth rendering to get past 403/bot walls.
4. Your client never talks to Google/Bing directly — SearXNG does, spreading
   the load and hiding your scraping activity from upstream engines.

Everything stays under **one MCP server**, so your agent gets a single, clean
tool surface: `web_research`, `search_urls`, `scrape_url`, `engine_status`.

---

## What's in this repo

```text
.
├── README.md                      # this file
├── requirements.txt               # runtime dependencies
├── requirements-dev.txt           # test dependencies
├── pytest.ini                     # pytest config (asyncio + live marker)
├── engine/
│   ├── mcp_research_server.py     # MCP entry point (single server, 4 tools)
│   └── research/                  # engine package
│       ├── __init__.py            # public async API + engine_status
│       ├── config.py              # env-driven configuration
│       ├── logging_utils.py       # stderr logger (keeps stdio clean)
│       ├── cache.py               # thread-safe TTL disk cache
│       ├── search.py              # SearXNG + DDGS fusion, pagination, breaker
│       ├── fetch.py               # cascading fetchers (HTTP → JS → PDF)
│       ├── extract.py             # trafilatura → markdownify → pypdf
│       └── report.py              # final report shaping
├── searxng/
│   ├── docker-compose.yml         # SearXNG container (with healthcheck)
│   └── searxng/
│       ├── settings.yml           # engine roster + tuning (no real secrets)
│       └── limiter.toml           # bot-detection config for local use
├── skill/
│   └── SKILL.md                   # agent skill card (unlimited-research)
├── .kimi-code/
│   └── mcp.json                   # sample MCP registration
├── tests/
│   ├── test_cache.py              # unit: cache TTL/roundtrip/stats
│   ├── test_search.py             # unit: fusion, dedupe, circuit breaker
│   ├── test_fetch.py              # unit: cascade, escalation, cache
│   ├── test_extract.py            # unit: extraction + PDF
│   ├── test_report.py             # unit: report shaping
│   ├── test_end_to_end.py         # live: real SearXNG + internet
│   ├── mcp_e2e_check.py           # full MCP-protocol check over stdio
│   ├── stress_test.py             # burst/swarm/endurance stress (legacy)
│   └── stress_test_unlimited.py   # 6-phase unlimited/anti-bot stress
├── scripts/
│   └── engine_status.py           # CLI diagnostics
└── docs/
    ├── WEB_RESEARCH_SETUP.md      # operational notes
    └── ARCHITECTURE.md            # deep dive
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Python 3.10+ required (tested on 3.14). The JS-rendering tier needs a browser:

```bash
playwright install chromium
```

### 2. Start SearXNG

```bash
cd searxng
docker compose up -d
```

Verify:

```bash
curl -s "http://127.0.0.1:8081/search?format=json&q=test"
```

### 3. Register the MCP server

Point your MCP client at `engine/mcp_research_server.py`. For Kimi Code, merge
`.kimi-code/mcp.json` into `~/.kimi-code/mcp.json`. For other clients (Claude
Code, Kilo, etc.), register:

```json
{
  "mcpServers": {
    "unlimited-research": {
      "command": "python",
      "args": ["/absolute/path/to/engine/mcp_research_server.py"]
    }
  }
}
```

Restart your client or run `/reload`.

### 4. Use it

Four tools:

| Tool | What it does |
|------|--------------|
| `web_research` | Search + deep-scrape the top N results |
| `search_urls` | Search only — fused, deduped URLs/snippets |
| `scrape_url` | Scrape a single URL (HTML, JS, or PDF) |
| `engine_status` | Health, versions, config, cache stats |

Example `web_research`:

```json
{
  "query": "latest AI agent memory systems 2026",
  "num_results": 8,
  "max_content_length": 4000,
  "time_range": "y",
  "js_render": "auto"
}
```

`time_range`: `d` (day), `w` (week), `m` (month), `y` (year), or empty.
`js_render`: `auto` (browser only when the fast path fails), `always`, `never`.

---

## How it works end-to-end

1. **You send a query** to `web_research` (or `search_urls`).
2. The engine queries **SearXNG** (`http://127.0.0.1:8081`) and **DuckDuckGo**
   **in parallel** — SearXNG pages 1..10 in parallel per query, DDG rotates
   across backends with a politeness interval.
3. Results are **deduplicated** (canonicalized URLs) and **interleaved by rank**
   across the sources that responded — up to 200 per query.
4. Per-source **circuit breakers** skip any source that keeps failing, so a
   broken SearXNG container never blocks research.
5. For each URL, the engine runs the **fetch cascade**:
   - PDF? → download bytes (HTTP/2, with a TLS-impersonation fallback) → pypdf
     → text. PDFs without a `.pdf` extension (e.g. arXiv `/pdf/…`) are
     detected by `Content-Type`.
   - Else **Scrapling/curl_cffi** fetch with real-browser TLS/HTTP2 fingerprint
     impersonation (`impersonate="chrome"`) → trafilatura/markdownify extraction.
   - Too little content, or an anti-bot page? → real headless browser via
     **Crawl4AI/Playwright** with stealth patches + magic mode + anti-bot
     retries, one shared browser session for the whole run.
6. Results are cached on disk (10 min search, 6 h fetch) so repeat research is
   instant and upstream engines are never re-hit.
7. You get a JSON report: `sources_used`, and per source — rank, title, URL,
   snippet, search source, HTTP status, fetch method, cached flag, content
   length, extracted content, and any error.

Because all search traffic goes through your own SearXNG container, upstream
engines see SearXNG's IP — not your agent's — and load is spread across many
engines instead of hammering one.

---

## Why it avoids rate limits & bot detection

Search side:

- **Distributed search** — SearXNG queries many engines in parallel; each
  engine sees only a fraction of your volume. DDGS adds an independent second
  channel.
- **IP abstraction** — upstream engines see SearXNG's IP, not your host.
- **DDG backend rotation** — DuckDuckGo calls alternate between the
  `duckduckgo` and `duckduckgo_lite` backends with a configurable minimum
  interval, so anti-abuse throttling on one endpoint never blocks all DDG
  traffic.
- **SearXNG page retries** — transient page failures are retried with backoff
  before a source is ever marked down.

Fetch side:

- **TLS fingerprint impersonation** — the fast path speaks real Chrome
  JA3/JA4 TLS and HTTP/2 fingerprints via curl_cffi (through Scrapling), which
  is what defeats 403s keyed on the client handshake.
- **Stealth browser tier** — Crawl4AI runs with `enable_stealth`, `magic`
  mode, `max_retries`, and `wait_until="load"` so JS-challenged pages get
  rendered like a real user session.
- **Content-Type PDF detection** — PDFs served without a `.pdf` URL are routed
  to the pypdf path instead of crashing the browser tier.
- **HTTP/2 everywhere** — httpx PDF fetches negotiate HTTP/2 to match browser
  behavior.

Everywhere:

- **Caching** — repeated queries and pages are served from disk, hitting the
  network zero times.
- **Circuit breakers** — a source opens only after 3 consecutive failures and
  re-arms after 30s, so transient blips never gate research for long.

---

## Configuration

Everything is overridable via environment variables. Full table in
`docs/ARCHITECTURE.md`. The most useful ones:

| Env var | Default | Meaning |
|---------|---------|---------|
| `SEARXNG_URL` | `http://127.0.0.1:8081` | SearXNG instance |
| `SEARCH_SOURCES` | `searxng,ddgs` | fused sources in priority order |
| `SEARCH_MAX_RESULTS` | `200` | hard per-query bound (safety rail, not a cap) |
| `SEARXNG_MAX_PAGES` | `10` | max SearXNG pages fetched per query |
| `SEARXNG_RETRIES` | `2` | retries per SearXNG page before failure |
| `DDGS_BACKENDS` | `duckduckgo,duckduckgo_lite` | DDG backends to rotate |
| `DDGS_MIN_INTERVAL` | `0.5` | seconds between consecutive DDG calls |
| `SCRAPLING_IMPERSONATE` | `chrome` | curl_cffi TLS fingerprint for the fast path |
| `RESEARCH_JS_RENDER` | `auto` | `auto` / `always` / `never` browser tier |
| `RESEARCH_CRAWL4AI` | `true` | enable/disable the browser tier |
| `RESEARCH_CONCURRENCY` | `8` | max parallel page fetches |
| `RESEARCH_CACHE_DIR` | `~/.cache/unlimited-research` | cache location |
| `RESEARCH_PROXY` | *(empty)* | optional proxy for all fetches |
| `CIRCUIT_FAIL_THRESHOLD` | `3` | consecutive failures before a source opens |
| `CIRCUIT_COOLDOWN` | `30` | seconds a source stays open |

### SearXNG (`searxng/searxng/settings.yml`)

Engines enabled (all key-free): google, bing, duckduckgo, startpage, qwant,
brave, mojeek, yahoo, presearch, marginalia, wikipedia, google scholar,
crossref, pubmed. JSON format is enabled for the engine's JSON API. The
`secret_key` is the upstream `ultrasecretkey` placeholder — the container
entrypoint replaces it with a fresh random key on every start, so no real
secret is committed. Edit, then `docker compose restart` in `searxng/`.

---

## Testing & verification

```bash
# unit tests (no network needed)
python -m pytest -m "not live"

# live integration tests (needs SearXNG running + internet)
python -m pytest -m live

# full MCP-protocol E2E (spawns the real server, calls every tool over stdio)
python tests/mcp_e2e_check.py

# heavy unlimited stress — 6 phases:
python tests/stress_test_unlimited.py
```

`stress_test_unlimited.py` proves the "no limits, no bot walls" claims:

- **Phase A — coverage**: 6 queries × 200 results each (SearXNG paginated 10
  pages + DDG), verifying volume and domain diversity.
- **Phase B — mixed**: result sizes 20–50 with time-range filters.
- **Phase C — swarm**: 6 concurrent workers × 3 queries each.
- **Phase D — edge**: js_render always/never, extensionless PDF (arXiv),
  Cloudflare-protected URL (must degrade gracefully, never crash), empty
  query, invalid time_range, runaway `num_results` clamp.
- **Phase E — cache**: identical results served from cache, faster than cold.
- **Phase F — anti-bot**: rapid-fire scrapes of bot-protected/flaky sites —
  every request must resolve to a clean result, never an uncaught exception.

Blocked pages (403, Cloudflare, anti-bot walls, dead domains) are surfaced
per-result in the `error` field rather than failing the run.

---

## Limitations (honest)

- **Some walls cannot be fully bypassed**: sites that issue JS-only challenges
  requiring real interaction (some Cloudflare Turnstile, DataDome sessions),
  login walls, and IP-reputation blocks may still return 403 or empty content.
  The engine reports this cleanly instead of failing.
- **Heavy volume from one IP** can still get SearXNG's engines blocked. For
  serious volume, add more engines or point `RESEARCH_PROXY` at a proxy
  rotation.
- **CAPTCHAs** require human or third-party solving; not automated.
- **robots.txt / ToS** are the ethical and legal limits of any crawler.

---

## Replicating on a VPS

1. Clone this repo.
2. Install Docker, Docker Compose, Python 3.10+.
3. `pip install -r requirements.txt`
4. `cd searxng && docker compose up -d`
5. `curl "http://127.0.0.1:8081/search?format=json&q=test"` to confirm SearXNG.
6. Register `engine/mcp_research_server.py` with your MCP client.
7. Start researching.

---

## Credits / lineage

Originally built inside `Kimi_HQ` as `/skill:kimi-research`. Leveled up and
packaged here as a standalone, forkable engine with fused multi-source search,
a cascading HTML/JS/PDF fetch pipeline, disk caching, circuit breakers, and a
full test suite. The MCP server is renamed `unlimited-research`.
