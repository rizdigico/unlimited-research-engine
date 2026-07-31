#!/usr/bin/env python3
"""
Unlimited Research — no-API web research MCP server.

Single MCP server that exposes the full research stack (search, scrape,
deep-research, diagnostics) as four tools:

  - web_research      search + deep-scrape the top N results
  - search_urls       search only (fused, deduped URL lists)
  - scrape_url        scrape one URL (PDFs, HTML, JS-heavy pages)
  - engine_status     diagnostics / health

Search pipeline:  SearXNG (local meta-search) + DuckDuckGo, fused in parallel,
                  deduped, and interleaved by rank. Circuit breaker + disk cache
                  keep it fast and resilient.
Fetch pipeline:    Scrapling (stealthy HTTP) -> Crawl4AI/Playwright (JS render)
                  -> pypdf (PDF), with retries, backoff, and concurrency limits.

No external API keys required. Run from the repo root:

    python engine/mcp_research_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server

logger = logging.getLogger("research.mcp")
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from research import deep_research, engine_status, scrape_url, search_urls

app = Server("unlimited-research")


def _tool_spec(name: str, description: str, props: dict[str, Any], required: list[str]) -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={"type": "object", "properties": props, "required": required},
    )


_QUERY = {"type": "string", "description": "The research topic or search query."}
_TIME_RANGE = {
    "type": "string",
    "enum": ["", "d", "w", "m", "y"],
    "default": "",
    "description": "Time filter: d=day, w=week, m=month, y=year.",
}
_NUM_RESULTS = {
    "type": "integer",
    "default": 15,
    "minimum": 1,
    "maximum": 200,
    "description": "Number of top results to fetch and scrape (up to 200 for full web coverage).",
}
_NUM_URLS = {
    "type": "integer",
    "default": 20,
    "minimum": 1,
    "maximum": 200,
    "description": "Maximum number of URLs to return (up to 200 for full web coverage).",
}
_MAX_LEN = {
    "type": "integer",
    "default": 20000,
    "minimum": 500,
    "maximum": 500000,
    "description": "Maximum characters of extracted content per page.",
}
_JS_RENDER = {
    "type": "string",
    "enum": ["auto", "always", "never"],
    "default": "auto",
    "description": "auto=render in a browser only when the fast path fails; always=always render; never=never launch a browser.",
}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        _tool_spec(
            "web_research",
            (
                "Perform no-API deep web research on a topic. Searches a local SearXNG "
                "meta-search instance plus DuckDuckGo in parallel, fuses and dedupes results, "
                "then deep-scrapes each URL (HTML, JS-heavy SPAs, and PDFs supported). "
                "Returns a consolidated report with titles, URLs, snippets, and extracted content. "
                "No external API keys are required."
            ),
            {
                "query": _QUERY,
                "num_results": _NUM_RESULTS,
                "max_content_length": _MAX_LEN,
                "time_range": _TIME_RANGE,
                "js_render": _JS_RENDER,
            },
            ["query"],
        ),
        _tool_spec(
            "search_urls",
            (
                "Find relevant URLs for a query using local SearXNG meta-search plus "
                "DuckDuckGo, fused and deduplicated. Returns titles, URLs, snippets, and "
                "per-result source."
            ),
            {"query": _QUERY, "num_results": _NUM_URLS, "time_range": _TIME_RANGE},
            ["query"],
        ),
        _tool_spec(
            "scrape_url",
            (
                "Scrape a single URL and return its content as markdown or plain text. "
                "Handles HTML pages, JavaScript-heavy sites, and PDF documents."
            ),
            {
                "url": {"type": "string", "description": "URL to scrape."},
                "format": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
                "max_content_length": _MAX_LEN,
                "js_render": _JS_RENDER,
            },
            ["url"],
        ),
        _tool_spec(
            "engine_status",
            (
                "Diagnostics and health for the research engine: dependency versions and "
                "availability, live SearXNG reachability, active configuration, and cache stats."
            ),
            {},
            [],
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        return await _dispatch(name, arguments)
    except ValueError as exc:
        return [TextContent(type="text", text=json.dumps({"tool": name, "error": str(exc)}, indent=2, ensure_ascii=False))]
    except Exception as exc:
        logger.exception("tool=%s failed", name)
        return [TextContent(type="text", text=json.dumps({"tool": name, "error": f"{type(exc).__name__}: {exc}"}, indent=2, ensure_ascii=False))]


async def _dispatch(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "search_urls":
        result = await search_urls(
            arguments["query"],
            arguments.get("num_results", 20),
            arguments.get("time_range", ""),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "scrape_url":
        result = await scrape_url(
            arguments["url"],
            arguments.get("format", "markdown"),
            arguments.get("max_content_length", 20000),
            arguments.get("js_render", "auto"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "web_research":
        result = await deep_research(
            arguments["query"],
            arguments.get("num_results", 15),
            arguments.get("max_content_length", 20000),
            arguments.get("time_range", ""),
            arguments.get("js_render", "auto"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "engine_status":
        result = await engine_status()
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
