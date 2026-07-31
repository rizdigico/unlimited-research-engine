"""
True end-to-end MCP protocol test.

Spawns the real ``mcp_research_server.py`` as a subprocess, connects over the
stdio MCP transport exactly like a CLI would, lists the tools, and calls every
one of them with real arguments. This validates the full surface the agent
will use after the MCP is registered.

Run:
    python tests/mcp_e2e_check.py
"""

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER = REPO_ROOT / "engine" / "mcp_research_server.py"

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"TOOLS ({len(tool_names)}): {tool_names}")
            assert len(tool_names) == 4, f"expected 4 tools, got {tool_names}"
            for expected in ("web_research", "search_urls", "scrape_url", "engine_status"):
                assert expected in tool_names, f"missing tool {expected}"

            print("\n--- engine_status ---")
            res = await session.call_tool("engine_status", {})
            status = json.loads(res.content[0].text)
            print(json.dumps(status, indent=1)[:900])
            assert status["config"]["searxng_reachable"] is True
            assert status["availability"]["scrapling"] is True
            assert status["availability"]["crawl4ai"] is True
            assert status["availability"]["trafilatura"] is True

            print("\n--- search_urls ---")
            res = await session.call_tool("search_urls", {"query": "python async mcp server", "num_results": 5})
            search_out = json.loads(res.content[0].text)
            print(f"sources_used={search_out['sources_used']} results={len(search_out['results'])}")
            assert search_out["results"], "search_urls returned no results"

            print("\n--- scrape_url ---")
            res = await session.call_tool("scrape_url", {"url": "https://example.com", "format": "markdown", "max_content_length": 2000})
            scrape_out = json.loads(res.content[0].text)
            print(f"status={scrape_out['status']} method={scrape_out['method']} content_len={scrape_out['content_length']}")
            assert scrape_out["status"] == 200
            assert scrape_out["content"]

            print("\n--- web_research ---")
            res = await session.call_tool(
                "web_research",
                {"query": "open source headless browser automation 2026", "num_results": 3, "max_content_length": 1500, "time_range": ""},
            )
            research_out = json.loads(res.content[0].text)
            print(f"num_results={research_out['num_results']} sources_used={research_out['sources_used']}")
            assert research_out["num_results"] >= 1
            first = research_out["sources"][0]
            print(f"  #1 {first['url']} status={first['status']} method={first['fetch_method']} len={first['content_length']}")

            print("\nALL MCP E2E CHECKS PASSED")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
