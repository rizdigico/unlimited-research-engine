#!/usr/bin/env python3
"""
No-API web research MCP server for Kimi Code CLI.

Search strategy:
  1. Local SearXNG meta-search (unlimited, no API keys, rotates engines).
  2. Fall back to DuckDuckGo search (ddgs) if SearXNG is down.
  3. Use Scrapling to fetch/deep-scrape each result.

No external API keys required.
"""

import asyncio
import json
import sys
import urllib.parse
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

try:
    from ddgs import DDGS
except Exception as exc:  # pragma: no cover
    DDGS = None
    DDGS_ERROR = str(exc)

try:
    from scrapling.fetchers import Fetcher
    from markdownify import markdownify
except Exception as exc:  # pragma: no cover
    Fetcher = None
    markdownify = None
    FETCHER_ERROR = str(exc)

app = Server("kimi-research")

SEARXNG_BASE_URL = "http://127.0.0.1:8081"


def _normalize_searxng_results(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert SearXNG result objects to the same shape ddgs returns."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        url = item.get("url", "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "title": item.get("title", ""),
                "href": url,
                "body": item.get("content", ""),
                # Extras for debugging/aggregation
                "engines": item.get("engines", []),
                "score": item.get("score", 0),
            }
        )
    return out


async def _search_searxng(query: str, num_results: int, time_range: str = "") -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "format": "json",
        "q": query,
    }
    if time_range:
        # SearXNG time_range values: day, week, month, year
        params["time_range"] = {"d": "day", "w": "week", "m": "month", "y": "year"}.get(time_range, time_range)

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        resp = await client.get(f"{SEARXNG_BASE_URL}/search", params=params)
        resp.raise_for_status()
        data = resp.json()
        results = _normalize_searxng_results(data.get("results", []))
        return results[:num_results]


async def _search_ddgs(query: str, num_results: int, time_range: str) -> list[dict[str, Any]]:
    if DDGS is None:
        raise RuntimeError(f"ddgs not available: {DDGS_ERROR}")

    def _run():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=num_results, timelimit=time_range or None))

    return await asyncio.to_thread(_run)


async def _search(query: str, num_results: int, time_range: str) -> tuple[list[dict[str, Any]], str]:
    """Try SearXNG first, fall back to DuckDuckGo. Returns (results, source_label)."""
    try:
        results = await _search_searxng(query, num_results, time_range)
        if results:
            return results, "searxng"
    except Exception as exc:
        print(f"SearXNG search failed: {exc}", file=sys.stderr, flush=True)

    try:
        results = await _search_ddgs(query, num_results, time_range)
        return results, "ddgs"
    except Exception as exc:
        raise RuntimeError(f"Both SearXNG and DuckDuckGo search failed: {exc}")


async def _scrape_with_scrapling(url: str, fmt: str, max_len: int) -> dict[str, Any]:
    if Fetcher is None:
        raise RuntimeError(f"Scrapling Fetcher not available: {FETCHER_ERROR}")

    def _run():
        try:
            page = Fetcher.get(url, stealthy_headers=True, follow_redirects=True)
            if fmt == "text":
                content = page.get_all_text()
            else:
                content = markdownify(page.html_content) if markdownify else page.get_all_text()
            # Extract title from HTML if available
            title = ""
            try:
                title_tag = page.find('title')
                if title_tag:
                    title = title_tag.text.strip()
            except Exception:
                pass
            return {
                "url": url,
                "status": page.status,
                "title": title,
                "content": content[:max_len],
                "error": None,
            }
        except Exception as e:
            return {"url": url, "status": 0, "title": "", "content": "", "error": str(e)}

    return await asyncio.to_thread(_run)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="web_research",
            description=(
                "Perform no-API web research on a topic. "
                "Uses a local SearXNG meta-search first, falls back to DuckDuckGo, "
                "then scrapes each result with Scrapling. "
                "Returns a consolidated report with titles, URLs, and extracted content. "
                "No external API keys are required."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The research topic or search query.",
                    },
                    "num_results": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 15,
                        "description": "Number of top results to fetch and scrape.",
                    },
                    "max_content_length": {
                        "type": "integer",
                        "default": 8000,
                        "minimum": 500,
                        "maximum": 50000,
                        "description": "Maximum characters of content to extract per page.",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["", "d", "w", "m", "y"],
                        "default": "",
                        "description": "Time filter: d=day, w=week, m=month, y=year.",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_urls",
            description=(
                "Find relevant URLs for a query using local SearXNG meta-search, "
                "falling back to DuckDuckGo. Returns titles, URLs, and snippets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "num_results": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 30,
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["", "d", "w", "m", "y"],
                        "default": "",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="scrape_url",
            description=(
                "Scrape a single URL using Scrapling and return its content as markdown or text."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to scrape."},
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "text"],
                        "default": "markdown",
                    },
                    "max_content_length": {
                        "type": "integer",
                        "default": 8000,
                        "minimum": 500,
                        "maximum": 50000,
                    },
                },
                "required": ["url"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "search_urls":
        results, source = await _search(
            arguments["query"],
            arguments.get("num_results", 10),
            arguments.get("time_range", ""),
        )
        return [TextContent(type="text", text=json.dumps({"source": source, "results": results}, indent=2))]

    if name == "scrape_url":
        result = await _scrape_with_scrapling(
            arguments["url"],
            arguments.get("format", "markdown"),
            arguments.get("max_content_length", 8000),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "web_research":
        query = arguments["query"]
        num_results = arguments.get("num_results", 5)
        max_len = arguments.get("max_content_length", 8000)
        time_range = arguments.get("time_range", "")

        urls, source = await _search(query, num_results, time_range)
        scrape_tasks = [
            _scrape_with_scrapling(u["href"], "markdown", max_len) for u in urls
        ]
        scraped = await asyncio.gather(*scrape_tasks, return_exceptions=True)

        output: list[dict[str, Any]] = []
        for idx, item in enumerate(urls):
            scr = scraped[idx]
            if isinstance(scr, Exception):
                scr_data = {"status": 0, "error": str(scr), "content": ""}
            else:
                scr_data = scr
            output.append(
                {
                    "rank": idx + 1,
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                    "status": scr_data.get("status", 0),
                    "content": scr_data.get("content", ""),
                    "error": scr_data.get("error"),
                }
            )

        return [TextContent(type="text", text=json.dumps({"query": query, "source": source, "sources": output}, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
