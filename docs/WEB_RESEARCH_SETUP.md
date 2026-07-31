# Unlimited No-API Web Research — Setup & Operations

## What this is
A single self-hosted, no-API-key, rate-limit-resistant research stack exposed as
one MCP server (`unlimited-research`). All research lives under one MCP.

- Search: local **SearXNG** meta-search + **DuckDuckGo**, fused in parallel,
  deduplicated by canonical URL, interleaved by rank. Circuit breakers and a
  disk cache keep it fast and resilient.
- Scrape: **Scrapling** (stealthy HTTP) → **Crawl4AI/Playwright** (JS-heavy
  SPAs) → **pypdf** (PDFs), with retries, backoff, concurrency limits, and an
  optional proxy.
- Extract: **trafilatura** readability → **markdownify** fallback.
- No API keys. No external AI models.

## Location
- Repo: `C:\Users\aariz\kilo_HQ\unlimited-research-engine`
- MCP entry: `engine\mcp_research_server.py`
- SearXNG container: `searxng\docker-compose.yml` (port `127.0.0.1:8081`)

## Install (one-time)
```powershell
cd C:\Users\aariz\kilo_HQ\unlimited-research-engine
pip install -r requirements.txt
```

## Start SearXNG (required for the primary search source)
```powershell
cd C:\Users\aariz\kilo_HQ\unlimited-research-engine\searxng
docker compose up -d

# verify
curl -s "http://127.0.0.1:8081/search?format=json&q=test"
```

## MCP registration
The MCP server is registered in the CLI config under the key `unlimited-research`
pointing at `engine\mcp_research_server.py`. After editing config or code,
restart the CLI (or run `/reload`) for it to take effect.

## Available tools (after reload)
- `mcp__unlimited_research__web_research` — query → fused URLs → deep-scraped content
- `mcp__unlimited_research__search_urls` — query → URLs/snippets only
- `mcp__unlimited_research__scrape_url` — scrape a single URL (HTML/JS/PDF)
- `mcp__unlimited_research__engine_status` — health/diagnostics

## Example arguments
```json
{
  "query": "latest AI agent memory systems 2026",
  "num_results": 8,
  "max_content_length": 4000,
  "time_range": "m",
  "js_render": "auto"
}
```
`time_range`: `d`/`w`/`m`/`y` or empty. `js_render`: `auto`/`always`/`never`.

## Diagnostics
```powershell
cd C:\Users\aariz\kilo_HQ\unlimited-research-engine
python scripts\engine_status.py
```

## Tests
```powershell
# unit tests (no network)
python -m pytest -m "not live"

# live integration + end-to-end (needs SearXNG + internet)
python -m pytest -m live

# full MCP protocol check (spawns the real server over stdio)
python tests\mcp_e2e_check.py

# heavy stress (burst + swarm + endurance)
python tests\stress_test.py
```

## SearXNG management
```powershell
cd C:\Users\aariz\kilo_HQ\unlimited-research-engine\searxng
docker compose up -d      # start
docker compose restart    # restart (picks up settings.yml changes)
docker compose down       # stop
```

## Config overrides (env vars)
See `docs/ARCHITECTURE.md` for the full table (`SEARXNG_URL`, `RESEARCH_JS_RENDER`,
`RESEARCH_CONCURRENCY`, `RESEARCH_CACHE_DIR`, `RESEARCH_PROXY`, ...).

## Expected failures
Upstream blocking is normal and handled: 403/Cloudflare pages, dead domains,
and anti-bot walls surface per-result in the `error` field without aborting a
research run. Dead domains are retried with backoff and then skipped.
