"""
Heavy stress test for the unlimited research engine.

Three phases:
  1. BURST   — all queries launched concurrently through `deep_research`.
  2. SWARM   — N parallel workers each treating the engine as an independent task.
  3. ENDURANCE — sequential loop of the full query set (cache-warmed + cold).

Each phase exercises the real stack end-to-end: fused search (SearXNG + DDGS),
cascade fetch (Scrapling / Crawl4AI / pypdf), extraction, caching, and reporting.

Run:
    python tests/stress_test.py
    pytest -m live -k stress            (if wired as a live test)

Exit code 0 only when every phase reports 100% success on the search side.
Per-page failures (upstream 403s/empty pages) are counted and reported but do
not fail the run — that is the expected real-world behavior.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

from research import deep_research  # noqa: E402
from research.config import SEARXNG_URL  # noqa: E402

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


async def one(query: str, idx: int, num_results: int = 10, max_len: int = 4000) -> dict:
    start = time.time()
    try:
        report = await deep_research(query, num_results, max_len, time_range="", js_render="auto")
        sources = report["sources"]
        ok_scrapes = sum(1 for s in sources if s.get("status") == 200 and s.get("content"))
        errors = [
            {
                "rank": s.get("rank"),
                "url": s.get("url"),
                "status": s.get("status"),
                "content_length": s.get("content_length"),
                "error": s.get("error"),
            }
            for s in sources
            if s.get("error") or not s.get("content")
        ]
        return {
            "idx": idx,
            "query": query,
            "ok": True,
            "sources_used": report.get("sources_used"),
            "num_results": report.get("num_results"),
            "ok_scrapes": ok_scrapes,
            "errors": errors,
            "elapsed": round(time.time() - start, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {"idx": idx, "query": query, "ok": False, "error": str(exc), "elapsed": round(time.time() - start, 2)}


async def phase_burst() -> dict:
    print("\n=== PHASE 1: BURST (all queries concurrent, cold cache) ===")
    start = time.time()
    results = await asyncio.gather(*[one(q, i) for i, q in enumerate(QUERIES)])
    ok = sum(1 for r in results if r["ok"])
    total_pages = sum(r.get("num_results", 0) for r in results)
    ok_pages = sum(r.get("ok_scrapes", 0) for r in results)
    print(f"  {ok}/{len(results)} queries OK in {time.time() - start:.1f}s | {ok_pages}/{total_pages} pages scraped OK")
    for r in results:
        if not r["ok"]:
            print(f"  FAIL: {r}")
    return {"ok": ok, "total": len(results), "ok_pages": ok_pages, "total_pages": total_pages}


async def phase_swarm(workers: int = 8) -> dict:
    print(f"\n=== PHASE 2: SWARM ({workers} parallel independent workers, 2 queries each) ===")
    start = time.time()
    tasks = []
    for w in range(workers):
        for j in range(2):
            q = QUERIES[(w * 2 + j) % len(QUERIES)]
            tasks.append(one(q, w * 100 + j, num_results=8, max_len=3000))
    results = await asyncio.gather(*tasks)
    ok = sum(1 for r in results if r["ok"])
    total_pages = sum(r.get("num_results", 0) for r in results)
    ok_pages = sum(r.get("ok_scrapes", 0) for r in results)
    print(f"  {ok}/{len(tasks)} worker-runs OK in {time.time() - start:.1f}s | {ok_pages}/{total_pages} pages scraped OK")
    for r in results:
        if not r["ok"]:
            print(f"  FAIL: {r}")
    return {"ok": ok, "total": len(tasks), "ok_pages": ok_pages, "total_pages": total_pages}


async def phase_endurance(loops: int = 3) -> dict:
    print(f"\n=== PHASE 3: ENDURANCE (sequential, {loops}x, cache-warming) ===")
    start = time.time()
    ok = 0
    total = 0
    pages_ok = 0
    pages_total = 0
    for round_num in range(loops):
        for i, q in enumerate(QUERIES):
            total += 1
            r = await one(q, total, num_results=6, max_len=2500)
            if r["ok"]:
                ok += 1
                pages_ok += r.get("ok_scrapes", 0)
                pages_total += r.get("num_results", 0)
            else:
                print(f"  FAIL round {round_num + 1}: {r}")
    print(f"  {ok}/{total} OK in {time.time() - start:.1f}s | {pages_ok}/{pages_total} pages scraped OK")
    return {"ok": ok, "total": total, "ok_pages": pages_ok, "total_pages": pages_total}


async def main() -> int:
    print(f"=== Unlimited Research Engine — Heavy Stress Test ===")
    print(f"SearXNG target: {SEARXNG_URL}")
    burst = await phase_burst()
    swarm = await phase_swarm()
    endurance = await phase_endurance()

    print("\n=== SUMMARY ===")
    summary = {
        "burst": burst,
        "swarm": swarm,
        "endurance": endurance,
    }
    print(json.dumps(summary, indent=2))

    all_queries_ok = all(p["ok"] == p["total"] for p in (burst, swarm, endurance))
    total_pages = burst["total_pages"] + swarm["total_pages"] + endurance["total_pages"]
    ok_pages = burst["ok_pages"] + swarm["ok_pages"] + endurance["ok_pages"]
    print(f"\nQueries OK: {burst['ok'] + swarm['ok'] + endurance['ok']}/{burst['total'] + swarm['total'] + endurance['total']}")
    print(f"Pages scraped OK: {ok_pages}/{total_pages} ({100.0 * ok_pages / total_pages:.1f}%)")
    print("RESULT:", "PASS" if all_queries_ok else "FAIL")
    return 0 if all_queries_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
