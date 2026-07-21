---
name: kimi-research
description: Perform deep, unlimited, no-API web research using the local SearXNG + Scrapling stack in Kimi_HQ.
---

# kimi-research

One-shot deep web research skill. Lives entirely in `C:/Users/aariz/Kimi_HQ`.
No API keys. No external AI models. No DuckDuckGo rate-limit worries.

## What it does
- Searches a local **SearXNG** meta-search instance (`http://127.0.0.1:8081`) first.
- Falls back to DuckDuckGo (`ddgs`) if SearXNG is unavailable.
- Deep-scrapes the top result pages with **Scrapling**.
- Returns a consolidated JSON report with titles, URLs, snippets, and extracted markdown content.

## When to use
- The user asks for "research", "deep research", "find resources", "latest info", or any open-ended web lookup.
- You want to gather source material before summarizing or writing.
- You want to avoid API costs or rate limits.

## How to invoke
Call the single bundled tool:

```json
{
  "query": "latest AI agent memory systems 2026",
  "num_results": 8,
  "max_content_length": 3000,
  "time_range": "m"
}
```

Tool name:
- `mcp__kimi_research__web_research`

## Arguments
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `query` | string | required | Research topic or question. |
| `num_results` | integer | 5 | Number of top URLs to fetch and scrape (1-15). |
| `max_content_length` | integer | 8000 | Max characters of extracted content per page (500-50000). |
| `time_range` | string | "" | Time filter: `"d"`=day, `"w"`=week, `"m"`=month, `"y"`=year. |

## Response format
Top-level JSON fields:
- `query` — the original query
- `source` — `"searxng"` or `"ddgs"`
- `sources` — array of results, each with `rank`, `title`, `url`, `snippet`, `status`, `content`, `error`

## Prerequisite
SearXNG container must be running. If it isn't, start it:

```bash
cd C:/Users/aariz/Kimi_HQ/searxng
docker compose up -d
```

## Stack files
- `C:/Users/aariz/Kimi_HQ/mcp_research_server.py` — MCP server
- `C:/Users/aariz/Kimi_HQ/searxng/docker-compose.yml` — SearXNG container
- `C:/Users/aariz/Kimi_HQ/searxng/searxng/settings.yml` — SearXNG config
- `C:/Users/aariz/Kimi_HQ/WEB_RESEARCH_SETUP.md` — full setup notes

## Example prompt to the tool
"Research the current state of AI agent memory frameworks in 2026, find 8 authoritative sources, extract 2000 chars per page."
