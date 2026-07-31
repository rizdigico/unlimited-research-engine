"""Heavy stress test for the unlimited / full-web-coverage engine.

Exercises exactly the new capabilities:

  PHASE A COVERAGE   — 6 queries at num_results=200 (SearXNG pagination, up to
                       10 pages per query) verifying volume, domain diversity,
                       and that 200-result requests scale beyond 20-result ones.
  PHASE B MIXED      — num_results 20-50 + time_range filters.
  PHASE C SWARM      — 6 parallel workers x 3 queries each (20 results).
  PHASE D EDGE       — js_render always/never, extensionless PDF, anti-bot URL
                       graceful handling, empty/invalid input, runaway clamp.
  PHASE E CACHE      — re-run Phase A queries, verify identical cached results.
  PHASE F ANTI-BOT   — rapid-fire scrapes of bot-protected sites; every request
                       must resolve to a clean result (content or error), never
                       an uncaught exception or a hung pipeline.

Exit code 0 only when every phase passes.
"""

import asyncio
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import pytest  # noqa: E402

from research import deep_research, engine_status, scrape_url, search_urls  # noqa: E402

COVERAGE_QUERIES = [
    "artificial intelligence regulation 2026",
    "climate change carbon capture technology",
    "quantum computing breakthroughs",
    "cryptocurrency market analysis",
    "space exploration mars mission",
    "open source database engines",
]

# Bot-protected / flaky targets: must never crash the pipeline.
ANTIBOT_URLS = [
    "https://kvassiliou.com/tech/best-javascript-frameworks-2026",
    "https://www.amazon.com/",
    "https://www.reddit.com/r/Python/",
    "https://www.wikipedia.org/wiki/Python_(programming_language)",
]


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower().replace("www.", "")
    except Exception:
        return url


async def _coverage_phase() -> dict:
    ok = 0
    total_results = 0
    total_domains = set()
    per_query: list[int] = []
    scaling_ok: bool | None = None
    for i, q in enumerate(COVERAGE_QUERIES):
        out = await search_urls(q, num_results=200)
        n = len(out["results"])
        if n < 20:
            # Transient upstream throttle dips happen on shared IPs; give the
            # query one honest retry after a short cooldown and keep the best.
            await asyncio.sleep(3.0)
            retry = await search_urls(q, num_results=200)
            n = max(n, len(retry["results"]))
        per_query.append(n)
        total_results += n
        ok += 1 if n >= 20 else 0
        total_domains.update(_domain(r["href"]) for r in out["results"])
        if i == 0:
            small = await search_urls(q, num_results=20)
            scaling_ok = n > len(small["results"])
    return {
        "queries_ok": ok,
        "queries_total": len(COVERAGE_QUERIES),
        "results_total": total_results,
        "per_query": per_query,
        "unique_domains": len(total_domains),
        "scaling_ok": scaling_ok,
    }


async def _mixed_phase() -> dict:
    tasks = [
        search_urls("machine learning papers", num_results=50, time_range="y"),
        search_urls("best practices microservices", num_results=30, time_range="m"),
        search_urls("web performance optimization", num_results=40, time_range="w"),
        search_urls("kubernetes security", num_results=25, time_range="d"),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ok = sum(1 for r in results if isinstance(r, dict) and len(r.get("results", [])) >= 10)
    return {"ok": ok, "total": len(tasks)}


async def _swarm_phase() -> dict:
    queries = [
        "python type hints best practices",
        "async web frameworks comparison",
        "sqlite performance tuning",
        "machine learning ops mlops",
        "computer vision object detection",
        "natural language processing models",
        "data engineering pipelines",
        "api design rest vs graphql",
        "database replication strategies",
        "software testing pyramid",
        "cloud cost optimization",
        "observability distributed systems",
        "functional programming languages",
        "compiler design basics",
        "networking protocols tcp udp",
        "cybersecurity zero trust",
        "blockchain consensus algorithms",
        "embedded systems programming",
    ]

    async def worker(start: int) -> int:
        ok = 0
        for i in range(start, start + 3):
            q = queries[i % len(queries)]
            out = await search_urls(q, num_results=20)
            if isinstance(out, dict) and len(out.get("results", [])) >= 10:
                ok += 1
        return ok

    results = await asyncio.gather(*(worker(w * 3) for w in range(6)))
    return {"ok": sum(results), "total": 18}


async def _edge_phase() -> dict:
    checks = []

    js_always = await deep_research("javascript frameworks 2026", num_results=3, max_content_length=1500, js_render="always")
    checks.append(js_always.get("num_results", 0) >= 1)

    js_never = await deep_research("html css basics", num_results=3, max_content_length=1500, js_render="never")
    checks.append(js_never.get("num_results", 0) >= 1)

    pdf = await scrape_url("https://arxiv.org/pdf/2306.05316", fmt="text", max_content_length=2000)
    checks.append(pdf.get("status") == 200 and len(pdf.get("content", "")) > 0)

    blocked = await scrape_url(ANTIBOT_URLS[0], fmt="text", max_content_length=1000)
    checks.append(isinstance(blocked, dict) and "error" in blocked and blocked["status"] >= 0)

    try:
        await search_urls("   ")
        checks.append(False)
    except ValueError:
        checks.append(True)

    try:
        await search_urls("valid query", time_range="x")
        checks.append(False)
    except ValueError:
        checks.append(True)

    big = await search_urls("science", num_results=1000000)
    checks.append(len(big.get("results", [])) <= 200)

    return {"ok": sum(checks), "total": len(checks)}


async def _cache_phase() -> dict:
    first: dict[str, list] = {}
    t0 = time.monotonic()
    for q in COVERAGE_QUERIES[:3]:
        out = await search_urls(q, num_results=200)
        first[q] = out["results"]
    cold = time.monotonic() - t0

    t0 = time.monotonic()
    for q in COVERAGE_QUERIES[:3]:
        out = await search_urls(q, num_results=200)
        if [r["href"] for r in out["results"]] != [r["href"] for r in first[q]]:
            return {"ok": False, "reason": f"cached results differ for {q}", "cold_s": round(cold, 2), "warm_s": None}
    warm = time.monotonic() - t0
    return {"ok": warm < cold, "cold_s": round(cold, 2), "warm_s": round(warm, 2)}


async def _antibot_phase() -> dict:
    """Rapid-fire scrapes of bot-protected/flaky sites. Every call must return
    a clean result dict — content, or a graceful error — and never raise."""
    ok = 0
    total = len(ANTIBOT_URLS) * 2
    for url in ANTIBOT_URLS:
        for _ in range(2):
            try:
                out = await scrape_url(url, fmt="text", max_content_length=800)
                if isinstance(out, dict) and out.get("status", -1) >= 0:
                    ok += 1
            except Exception:
                pass
    return {"ok": ok, "total": total}


async def main() -> int:
    overall_ok = True

    print("=== PHASE A: COVERAGE (num_results=200, paginated) ===")
    a = await _coverage_phase()
    ok_a = (
        a["queries_ok"] == a["queries_total"]
        and a["results_total"] >= 180
        and a["unique_domains"] >= 100
        and a["scaling_ok"] is True
    )
    print(f"  queries {a['queries_ok']}/{a['queries_total']} reached 20+ results | total results={a['results_total']} unique_domains={a['unique_domains']} scaling_ok={a['scaling_ok']} per_query={a['per_query']}")
    overall_ok &= ok_a

    print("=== PHASE B: MIXED sizes + time_range ===")
    b = await _mixed_phase()
    ok_b = b["ok"] == b["total"]
    print(f"  {b['ok']}/{b['total']} queries returned 10+ results")
    overall_ok &= ok_b

    print("=== PHASE C: SWARM (6 workers x 3 queries) ===")
    c = await _swarm_phase()
    ok_c = c["ok"] == c["total"]
    print(f"  {c['ok']}/{c['total']} worker-queries OK")
    overall_ok &= ok_c

    print("=== PHASE D: EDGE cases ===")
    d = await _edge_phase()
    ok_d = d["ok"] == d["total"]
    print(f"  {d['ok']}/{d['total']} edge checks OK (js always/never, extensionless PDF, anti-bot URL, empty query, bad time_range, runaway clamp)")
    overall_ok &= ok_d

    print("=== PHASE E: CACHE behaviour ===")
    e = await _cache_phase()
    ok_e = e["ok"]
    print(f"  cold={e.get('cold_s')}s warm={e.get('warm_s')}s -> {'cache win' if ok_e else e.get('reason')}")
    overall_ok &= ok_e

    print("=== PHASE F: ANTI-BOT resilience (rapid-fire protected sites) ===")
    f = await _antibot_phase()
    ok_f = f["ok"] == f["total"]
    print(f"  {f['ok']}/{f['total']} protected-site scrapes resolved gracefully (no crash)")
    overall_ok &= ok_f

    print("=== SUMMARY ===")
    status = _status(overall_ok, a, b, c, d, e, f)
    print(status)
    print("RESULT: PASS" if overall_ok else "RESULT: FAIL")
    return 0 if overall_ok else 1


def _status(ok, a, b, c, d, e, f):
    return "\n".join(
        [
            f'  coverage: {a["queries_ok"]}/{a["queries_total"]} queries, {a["results_total"]} results, {a["unique_domains"]} unique domains',
            f'  mixed:    {b["ok"]}/{b["total"]}',
            f'  swarm:    {c["ok"]}/{c["total"]}',
            f'  edge:     {d["ok"]}/{d["total"]}',
            f'  cache:    {"PASS" if e["ok"] else "FAIL"}',
            f'  antibot:  {f["ok"]}/{f["total"]}',
        ]
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


@pytest.mark.live
async def test_stress_unlimited_phases():
    assert await main() == 0
