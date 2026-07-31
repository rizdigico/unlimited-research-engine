---
name: unlimited-research
description: Perform deep, unlimited, no-API web research using the local SearXNG + Crawl4AI + Scrapling engine (kilo_HQ/unlimited-research-engine).
---

# unlimited-research

One-shot deep web research skill backed by the `unlimited-research` MCP server.
No API keys. No external AI models. No client-side rate limits.

## What it does
- Searches a local **SearXNG** meta-search instance (`http://127.0.0.1:8081`)
  plus **DuckDuckGo** in parallel, fuses and dedupes results by canonical URL.
- Deep-scrapes the top result pages with a cascade:
  **Scrapling** (stealthy HTTP) → **Crawl4AI/Playwright** (JS-heavy SPAs) →
  **pypdf** (PDF documents).
- Extracts clean markdown via **trafilatura** (readability) with markdownify fallback.
- Returns a consolidated JSON report with titles, URLs, snippets, content,
  fetch method, and per-result source.

## When to use
- The user asks for "research", "deep research", "find resources", "latest info",
  or any open-ended web lookup.
- You want to gather source material before summarizing or writing.
- You want to avoid API costs or rate limits.

## How to invoke
Call the single bundled MCP server (all research lives under one MCP):

Tools:
- `mcp__unlimited_research__web_research` — search + deep-scrape top N results
- `mcp__unlimited_research__search_urls` — search only, URLs/snippets
- `mcp__unlimited_research__scrape_url` — scrape one URL (HTML/JS/PDF)
- `mcp__unlimited_research__engine_status` — health/diagnostics

Example `web_research`:
```json
{
  "query": "latest AI agent memory frameworks 2026",
  "num_results": 8,
  "max_content_length": 4000,
  "time_range": "m",
  "js_render": "auto"
}
```

## Arguments
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `query` | string | required | Research topic or question. |
| `num_results` | integer | 5 | Number of top URLs to fetch and scrape (1-15). |
| `max_content_length` | integer | 8000 | Max chars of extracted content per page (500-50000). |
| `time_range` | string | "" | `"d"`=day, `"w"`=week, `"m"`=month, `"y"`=year. |
| `js_render` | string | "auto" | `auto`/`always`/`never` browser rendering. |

## Response format
Top-level JSON fields:
- `query` — the original query
- `sources_used` — list of search sources that contributed (`searxng`, `ddgs`)
- `num_results` — count of scraped sources
- `sources` — array with `rank`, `title`, `url`, `snippet`, `source`,
  `status`, `fetch_method`, `cached`, `content_length`, `content`, `error`

## Prerequisites
1. SearXNG container must be running:
   ```bash
   cd C:/Users/aariz/kilo_HQ/unlimited-research-engine/searxng
   docker compose up -d
   ```
2. Python deps installed once:
   ```bash
   cd C:/Users/aariz/kilo_HQ/unlimited-research-engine
   pip install -r requirements.txt
   ```

## Stack files
- `C:/Users/aariz/kilo_HQ/unlimited-research-engine/engine/mcp_research_server.py` — MCP server
- `C:/Users/aariz/kilo_HQ/unlimited-research-engine/engine/research/` — engine package
- `C:/Users/aariz/kilo_HQ/unlimited-research-engine/searxng/` — SearXNG container + config
- `C:/Users/aariz/kilo_HQ/unlimited-research-engine/README.md` — full docs

## Example prompt to the tool
"Research the current state of AI agent memory frameworks in 2026, find 8 authoritative sources, extract 4000 chars per page."
