# Unlimited No-API Web Research Engine

A self-hosted, no-API-key, rate-limit-resistant web research stack built from:

- **SearXNG** — local meta-search engine that queries Google, Bing, DuckDuckGo, Brave, Startpage, Qwant, Wikipedia, etc.
- **Scrapling** — anti-bot page fetcher and HTML→markdown extractor.
- **DuckDuckGo Search (`ddgs`)** — fallback if SearXNG is unavailable.
- **MCP Server** — exposes `web_research`, `search_urls`, and `scrape_url` tools to any MCP client (Kimi Code CLI, Claude Code, etc.).

> No paid API keys. No external AI models. No search-engine rate limits on your client side.

---

## Why this exists

Most "deep research" tools rely on paid APIs (OpenAI, Google, Bing, Perplexity) and quickly hit rate limits or costs. This engine removes all of that by:

1. Running a local **SearXNG** container that fans your query across many free upstream search engines.
2. **Deep-scraping** each result with Scrapling.
3. Falling back to DuckDuckGo directly if SearXNG ever goes down.

Your client never talks to Google/Bing directly — SearXNG does. That distributes request load and hides your scraping activity from the search engines.

---

## What's in this repo

```text
.
├── README.md                        # this file
├── requirements.txt                 # Python dependencies
├── engine/
│   └── mcp_research_server.py       # MCP server: search + scrape + fallback
├── searxng/
│   ├── docker-compose.yml           # SearXNG container definition
│   └── searxng/
│       ├── settings.yml             # active SearXNG config
│       ├── limiter.toml             # disables token bot-detection for local use
│       └── archive/
│           └── settings.yml.old     # previous settings snapshot
├── skill/
│   └── SKILL.md                     # Kimi Code skill card for /skill:kimi-research
├── .kimi-code/
│   └── mcp.json                     # sample MCP registration for Kimi Code CLI
├── tests/
│   └── stress_test.py               # swarm-style pressure test used to validate the engine
└── docs/
    └── WEB_RESEARCH_SETUP.md        # original Kimi_HQ setup notes
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start SearXNG

```bash
cd searxng
docker compose up -d
```

Wait a few seconds, then verify:

```bash
curl -s "http://127.0.0.1:8081/search?format=json&q=test"
```

### 3. Register the MCP server

For **Kimi Code CLI**, copy `.kimi-code/mcp.json` into `~/.kimi-code/mcp.json` (merge with existing servers), then restart Kimi Code or run `/reload`.

For **any other MCP client**, run the server directly:

```bash
python engine/mcp_research_server.py
```

### 4. Use it

Three tools are exposed:

| Tool | What it does |
|------|--------------|
| `web_research` | Search + deep scrape the top N results |
| `search_urls` | Search only — return URLs/snippets |
| `scrape_url` | Scrape a single URL |

Example `web_research` arguments:

```json
{
  "query": "latest AI agent memory systems 2026",
  "num_results": 8,
  "max_content_length": 4000,
  "time_range": "y"
}
```

`time_range` values: `d` (day), `w` (week), `m` (month), `y` (year), or empty.

---

## How it works end-to-end

1. **You send a query** to the MCP server (`mcp_research_server.py`).
2. The server **tries SearXNG first** at `http://127.0.0.1:8081/search?format=json&q=...`.
3. SearXNG queries its configured upstream engines (Google, Bing, DuckDuckGo, Startpage, Qwant, Wikipedia, Brave) and returns a merged JSON result list.
4. The server **deduplicates** URLs and picks the top N.
5. For each URL, the server spawns a concurrent **Scrapling fetch**, converting HTML to markdown and extracting the title.
6. If SearXNG fails entirely, the server **falls back to DuckDuckGo Search** (`ddgs`) to get the URLs.
7. The server returns a JSON report containing: query, source (`searxng` or `ddgs`), and for each result its rank, title, URL, snippet, HTTP status, extracted content, and any error.

Because all search traffic goes through your own SearXNG container, upstream engines see SearXNG's IP, not your client's, and the load is spread across many engines instead of hammering one.

---

## Why it avoids rate limits

- **Distributed search**: SearXNG queries many engines in parallel; each engine only sees a fraction of your total volume.
- **IP abstraction**: Upstream engines see the SearXNG container, not the host running your AI client.
- **Separate fetch layer**: Scrapling fetches pages directly from the target sites, not through search engines, so the "search quota" and "fetch quota" are decoupled.
- **DuckDuckGo fallback**: If SearXNG is down, `ddgs` is used directly so research can continue.

---

## Configuration

### SearXNG (`searxng/searxng/settings.yml`)

- `use_default_settings: true` keeps the default engine roster.
- `search.formats: [html, json]` enables JSON API responses.
- Engines enabled: `google`, `bing`, `duckduckgo`, `startpage`, `qwant`, `wikipedia`.

To add/remove engines or change behavior, edit this file and restart the container:

```bash
cd searxng
docker compose restart
```

### SearXNG rate limiter (`searxng/searxng/limiter.toml`)

```toml
[botdetection.ip_limit]
link_token = false
```

This disables the token-based bot-detection check so local/authenticated use is not blocked.

### MCP registration (`.kimi-code/mcp.json`)

```json
{
  "mcpServers": {
    "kimi-research": {
      "command": "python",
      "args": ["C:\\Users\\aariz\\Kimi_HQ\\mcp_research_server.py"]
    }
  }
}
```

Update the path to match where you cloned this repo.

---

## Limitations

- Some sites (Reddit, ACM, paywalled papers) return 403 or empty content — this is normal upstream blocking.
- Binary/PDF links may fail because the current extractor expects HTML/text.
- Heavy JavaScript SPAs may return empty content unless Scrapling's JS-aware path is used.
- SearXNG itself can still be blocked by upstream engines if heavily abused from one IP; rotate VPS IPs or add more engines in settings if that happens.

---

## Stress test results

This engine was validated with two kinds of load:

### Test 1 — Burst + endurance (single process)

- **15 concurrent deep-research queries**, each fetching up to 10 URLs and scraping 4,000 characters.
- **45 sequential deep-research queries** (same 15 queries × 3 loops).
- Result: **60/60 succeeded**, all sourced from SearXNG, no DuckDuckGo fallback needed.

### Test 2 — Swarm pressure test (`tests/stress_test.py`)

- **10 parallel workers**, each treating the engine as a separate research task.
- Each worker: `num_results=12`, `max_content_length=6000`, `time_range="y"`.
- All 10 workers completed successfully via SearXNG, most in 3–5 seconds, one in ~16 seconds due to a slow PDF link.

Overall scrape success rate was high; failures were isolated upstream blocks (403s on Reddit/ACM/SSRN, one UTF-8 decode failure on a `.pdf` link). These are expected and do not affect engine reliability.

---

## Replicating on a VPS

1. Clone this repo.
2. Install Docker, Docker Compose, and Python 3.10+.
3. `pip install -r requirements.txt`
4. `cd searxng && docker compose up -d`
5. `curl "http://127.0.0.1:8081/search?format=json&q=test"` to confirm SearXNG is up.
6. Register `engine/mcp_research_server.py` with your MCP client.
7. Start researching.

---

## Credits / lineage

Originally built inside `Kimi_HQ` for the `/skill:kimi-research` skill. Packaged here as a standalone, forkable engine.
