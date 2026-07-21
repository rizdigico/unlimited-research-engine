"""
Swarm-style stress test for the unlimited research engine.

Imports the engine functions directly from mcp_research_server.py and runs
many concurrent deep-research queries to validate SearXNG + Scrapling reliability.

Run:
    python tests/stress_test.py

Expected: every query succeeds via SearXNG; only isolated upstream blocks/PDFs fail.
"""

import asyncio
import sys
import time
import traceback
from pathlib import Path

# Add repo engine path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "engine"))

from mcp_research_server import _search, _scrape_with_scrapling

QUERIES = [
    "AI agent memory frameworks 2026 comparison",
    "agentic AI long-term memory vector stores",
    "multi-agent orchestration consensus protocols 2026",
    "LLM agent planning algorithms ReAct Reflexion 2026",
    "AI agent tool use benchmarks SWE-bench AgentBench",
    "autonomous AI agents safety alignment 2026",
    "AI agent retrieval augmented generation RAG architectures",
    "embodied AI agents simulators 2026",
    "AI agent evaluation metrics trajectory success rate",
    "open source AI agent platforms AutoGPT CrewAI 2026",
]


async def one(query: str, idx: int, num_results: int = 12, max_len: int = 6000):
    start = time.time()
    try:
        urls, source = await _search(query, num_results, "y")
        if not urls:
            return {"idx": idx, "query": query, "ok": False, "error": "no urls", "elapsed": time.time() - start}
        tasks = [_scrape_with_scrapling(u["href"], "markdown", max_len) for u in urls]
        scraped = await asyncio.gather(*tasks, return_exceptions=True)
        ok_scrapes = sum(
            1 for s in scraped
            if isinstance(s, dict) and s.get("status") == 200 and len(s.get("content", "")) > 0
        )
        errors = []
        for u, s in zip(urls, scraped):
            if isinstance(s, Exception):
                errors.append({"url": u["href"], "status": 0, "error": str(s)})
            elif s.get("status") != 200 or not s.get("content"):
                errors.append({"url": u["href"], "status": s.get("status"), "content_len": len(s.get("content", "")), "error": s.get("error")})
        return {
            "idx": idx,
            "query": query,
            "ok": True,
            "source": source,
            "urls": len(urls),
            "ok_scrapes": ok_scrapes,
            "errors": errors,
            "elapsed": round(time.time() - start, 2),
        }
    except Exception as e:
        return {"idx": idx, "query": query, "ok": False, "error": str(e), "trace": traceback.format_exc(), "elapsed": round(time.time() - start, 2)}


async def main():
    print("=== Unlimited Research Engine — Stress Test ===\n")
    # Burst: all queries at once
    burst_start = time.time()
    burst_tasks = [one(q, i) for i, q in enumerate(QUERIES)]
    burst_results = await asyncio.gather(*burst_tasks)
    burst_ok = sum(1 for r in burst_results if r["ok"])
    print(f"BURST: {burst_ok}/{len(burst_results)} queries succeeded in {time.time() - burst_start:.1f}s\n")
    for r in burst_results:
        print(r)

    # Endurance: loop queries sequentially
    print("\n=== Sequential endurance loop (3x) ===")
    seq_ok = 0
    seq_total = 0
    endurance_start = time.time()
    for round_num in range(3):
        for q in QUERIES:
            seq_total += 1
            res = await one(q, seq_total)
            if res["ok"]:
                seq_ok += 1
            else:
                print(f"FAIL round {round_num + 1}: {res}")
    print(f"SEQUENTIAL: {seq_ok}/{seq_total} succeeded in {time.time() - endurance_start:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
