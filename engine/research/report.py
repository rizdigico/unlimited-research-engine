"""Report shaping — turns search + scrape results into the final JSON structure
returned by the MCP tools."""

from __future__ import annotations

from typing import Any


def build_report(
    query: str,
    urls: list[dict[str, Any]],
    scraped: list[dict[str, Any]],
    sources_used: list[str],
) -> dict[str, Any]:
    """Assemble the deep-research report. ``scraped`` entries must line up with
    ``urls`` by index (gather preserves order)."""
    output: list[dict[str, Any]] = []
    for idx, item in enumerate(urls):
        scr = scraped[idx] if idx < len(scraped) else {}
        if not isinstance(scr, dict):
            scr = {}
        output.append(
            {
                "rank": item.get("rank", idx + 1),
                "title": item.get("title", ""),
                "url": item.get("href", ""),
                "snippet": item.get("body", ""),
                "source": item.get("source", ""),
                "publishedDate": item.get("publishedDate"),
                "status": scr.get("status", 0),
                "fetch_method": scr.get("method"),
                "cached": scr.get("cached", False),
                "content_length": scr.get("content_length", 0),
                "content": scr.get("content", ""),
                "error": scr.get("error"),
            }
        )
    return {
        "query": query,
        "sources_used": sources_used,
        "num_results": len(output),
        "sources": output,
    }
