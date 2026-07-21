# Unlimited No-API Web Research for Kimi Code CLI

## What was set up
- `~/.kimi-code/mcp.json` now has 3 MCP servers:
  1. `agentmemory` — cross-CLI persistent memory (unchanged)
  2. `scrapling` — anti-bot scraping/fetching
  3. `kimi-research` — custom no-API research server
- Custom server file: `Kimi_HQ/mcp_research_server.py`
- Local SearXNG meta-search container running on `127.0.0.1:8081`
- Research strategy: **SearXNG first** → DuckDuckGo fallback → Scrapling deep scrape.
- No API keys. No external AI models.

## How to activate
Restart Kimi Code or run `/reload` in the TUI.

## Available tools after reload
- `mcp__kimi_research__web_research` — query → top URLs → extracted markdown content
- `mcp__kimi_research__search_urls` — query → list of URLs/snippets only
- `mcp__kimi_research__scrape_url` — scrape a single URL

## Example arguments
```json
{
  "query": "latest AI agent memory systems 2026",
  "num_results": 5,
  "max_content_length": 2000,
  "time_range": "m"
}
```

## SearXNG management (Docker)
```bash
# Start / stop / restart
cd ~/Kimi_HQ/searxng
docker compose up -d
docker compose down
docker compose restart

# Check health
curl -s "http://127.0.0.1:8081/search?format=json&q=test" | python -m json.tool | head
```

## Why this avoids rate limits
- SearXNG queries many upstream engines (Google, Bing, Brave, DuckDuckGo, Startpage, Qwant, Wikipedia) and aggregates results.
- Each engine only sees SearXNG's requests, not your CLI's requests.
- If SearXNG is down, the server falls back to DuckDuckGo directly.
- Scrapling is used for fetching pages, not for search, so the search surface is large and distributed.

## Limitations
- SearXNG itself can still be blocked by upstream engines if overused, but it rotates engines and can be re-configured.
- Some JavaScript-heavy sites may need the `scrapling` MCP's browser fetchers instead.
- Content extraction is raw markdown; summarization is up to the model.
- SearXNG needs Docker running and uses ~300-500 MB RAM when idle.
