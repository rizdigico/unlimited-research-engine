import importlib

import pytest

from research.cache import DiskCache
from research.search import (
    CircuitBreaker,
    _fuse,
    canonical_url,
    search,
)

search_mod = importlib.import_module("research.search")


def test_canonical_url_dedupes_tracking_params():
    a = "https://Example.com/path/?utm_source=x&q=hello&utm_medium=y"
    b = "https://example.com/path?q=hello"
    assert canonical_url(a) == canonical_url(b)


def test_canonical_url_drops_fragment_and_slash():
    assert canonical_url("https://example.com/page/") == canonical_url("https://example.com/page")


def test_normalize_searxng_results_dedupes():
    raw = [
        {"url": "https://a.com", "title": "A", "content": "aa"},
        {"url": "https://a.com", "title": "A dup", "content": "aa2"},
        {"url": "https://b.com", "title": "B", "content": "bb"},
    ]
    out = search_mod._normalize_searxng_results(raw)
    assert len(out) == 2
    assert out[0]["source"] == "searxng"


def test_fuse_interleaves_and_dedupes():
    searxng = [
        {"href": "https://x.com", "title": "X", "source": "searxng"},
        {"href": "https://y.com", "title": "Y", "source": "searxng"},
    ]
    ddgs = [
        {"href": "https://x.com", "title": "X", "source": "ddgs"},  # dup
        {"href": "https://z.com", "title": "Z", "source": "ddgs"},
    ]
    merged = _fuse({"searxng": searxng, "ddgs": ddgs}, 10)
    urls = [m["href"] for m in merged]
    # Round-robin by rank: X (searxng r0), then ddgs r0 is a dup so skipped,
    # then Y (searxng r1) and Z (ddgs r1).
    assert urls == ["https://x.com", "https://y.com", "https://z.com"]
    assert all(m["rank"] == i + 1 for i, m in enumerate(merged))


def test_fuse_respects_num_results():
    searxng = [{"href": f"https://s{i}.com", "title": f"S{i}", "source": "searxng"} for i in range(5)]
    ddgs = [{"href": f"https://d{i}.com", "title": f"D{i}", "source": "ddgs"} for i in range(5)]
    merged = _fuse({"searxng": searxng, "ddgs": ddgs}, 3)
    assert len(merged) == 3


@pytest.mark.asyncio
async def test_search_fusion_mocked(monkeypatch, tmp_path):
    monkeypatch.setattr(
        search_mod,
        "SEARCH_CACHE",
        DiskCache("test", root=tmp_path, ttl=600),
    )

    async def fake_searxng(query, num, tr):
        return [{"href": "https://a.com", "title": "A", "body": "a", "source": "searxng"}]

    async def fake_ddgs(query, num, tr):
        return [{"href": "https://b.com", "title": "B", "body": "b", "source": "ddgs"}]

    monkeypatch.setattr(search_mod, "search_searxng", fake_searxng)
    monkeypatch.setattr(search_mod, "search_ddgs", fake_ddgs)

    results, sources = await search("q", num_results=5, time_range="")
    assert len(results) == 2
    assert set(sources) == {"searxng", "ddgs"}


@pytest.mark.asyncio
async def test_search_one_source_fails_still_works(monkeypatch, tmp_path):
    monkeypatch.setattr(
        search_mod,
        "SEARCH_CACHE",
        DiskCache("test", root=tmp_path, ttl=600),
    )

    async def failing_searxng(query, num, tr):
        raise RuntimeError("searxng down")

    async def fake_ddgs(query, num, tr):
        return [{"href": "https://b.com", "title": "B", "body": "b", "source": "ddgs"}]

    monkeypatch.setattr(search_mod, "search_searxng", failing_searxng)
    monkeypatch.setattr(search_mod, "search_ddgs", fake_ddgs)

    results, sources = await search("q", num_results=5, time_range="")
    assert len(results) == 1
    assert sources == ["ddgs"]


@pytest.mark.asyncio
async def test_search_all_fail_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(
        search_mod,
        "SEARCH_CACHE",
        DiskCache("test", root=tmp_path, ttl=600),
    )

    async def failing(query, num, tr):
        raise RuntimeError("down")

    monkeypatch.setattr(search_mod, "search_searxng", failing)
    monkeypatch.setattr(search_mod, "search_ddgs", failing)

    with pytest.raises(RuntimeError, match="all search sources failed"):
        await search("q", num_results=5, time_range="")


def test_circuit_breaker_opens_and_cools_down():
    cb = CircuitBreaker("test", fail_threshold=2, cooldown=0.05)
    assert cb.allow()
    cb.record_failure()
    assert cb.allow()
    cb.record_failure()
    assert not cb.allow()
    import time

    time.sleep(0.1)
    assert cb.allow()
    cb.record_success()
    cb.record_success()
    assert cb._consecutive_failures == 0
