import pytest

from research import fetch as fetch_mod
from research.cache import DiskCache
from research.fetch import fetch_url, _cascade_pdf


@pytest.fixture
def no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_mod, "FETCH_CACHE", DiskCache("test", root=tmp_path, ttl=600))


@pytest.mark.asyncio
async def test_pdf_fast_path(monkeypatch, no_cache):
    async def fake_pdf(url):
        return "PDF TEXT CONTENT", 200, None

    monkeypatch.setattr(fetch_mod, "_fetch_pdf", fake_pdf)
    result = await fetch_url("https://example.com/doc.pdf", "markdown", 8000)
    assert result["method"] == "pdf"
    assert result["content"] == "PDF TEXT CONTENT"
    assert result["status"] == 200
    assert result["error"] is None


@pytest.mark.asyncio
async def test_scrapling_success_no_escalation(monkeypatch, no_cache):
    good_html = "<html><head><title>T</title></head><body><article><h1>H</h1><p>" + "word " * 500 + "</p></article></body></html>"

    async def fake_scrapling(url):
        return {"url": url, "status": 200, "title": "T", "html": good_html, "method": "scrapling", "error": None}

    async def boom_js(url, fmt, session):
        raise AssertionError("js should not be called when fast path succeeds")

    monkeypatch.setattr(fetch_mod, "_fetch_scrapling", fake_scrapling)
    monkeypatch.setattr(fetch_mod, "_crawl_js", boom_js)
    monkeypatch.setattr(fetch_mod, "_js_enabled", lambda f: True)

    result = await fetch_url("https://example.com/page", "markdown", 8000)
    assert result["method"] == "scrapling"
    assert result["status"] == 200
    assert "word" in result["content"]


@pytest.mark.asyncio
async def test_scrapling_empty_escalates_to_js(monkeypatch, no_cache):
    async def fake_scrapling(url):
        return {"url": url, "status": 200, "title": "", "html": "<html></html>", "method": "scrapling", "error": None}

    async def fake_js(url, fmt, session):
        return {"url": url, "status": 200, "title": "JS T", "content": "RENDERED CONTENT " * 50, "content_length": 900, "method": "crawl4ai", "error": None}

    monkeypatch.setattr(fetch_mod, "_fetch_scrapling", fake_scrapling)
    monkeypatch.setattr(fetch_mod, "_crawl_js", fake_js)
    monkeypatch.setattr(fetch_mod, "_js_enabled", lambda f: True)

    result = await fetch_url("https://spa.example.com", "markdown", 8000)
    assert result["method"] == "crawl4ai"
    assert "RENDERED CONTENT" in result["content"]


@pytest.mark.asyncio
async def test_fetch_exception_returns_error_dict(monkeypatch, no_cache):
    async def boom_scrapling(url):
        raise RuntimeError("network unreachable")

    async def boom_js(url, fmt, session):
        raise RuntimeError("browser broken")

    monkeypatch.setattr(fetch_mod, "_fetch_scrapling", boom_scrapling)
    monkeypatch.setattr(fetch_mod, "_crawl_js", boom_js)
    monkeypatch.setattr(fetch_mod, "_js_enabled", lambda f: True)

    result = await fetch_url("https://example.com/x", "markdown", 8000)
    assert result["status"] == 0
    assert result["error"]


@pytest.mark.asyncio
async def test_fetch_cache_hit(monkeypatch, tmp_path):
    cache = DiskCache("test", root=tmp_path, ttl=600)
    monkeypatch.setattr(fetch_mod, "FETCH_CACHE", cache)

    good_html = "<html><body><p>" + "data " * 400 + "</p></body></html>"

    async def fake_scrapling(url):
        return {"url": url, "status": 200, "title": "T", "html": good_html, "method": "scrapling", "error": None}

    monkeypatch.setattr(fetch_mod, "_fetch_scrapling", fake_scrapling)
    monkeypatch.setattr(fetch_mod, "_js_enabled", lambda f: False)

    first = await fetch_url("https://example.com/page", "markdown", 8000)
    assert first["cached"] is False
    second = await fetch_url("https://example.com/page", "markdown", 8000)
    assert second["cached"] is True
    assert second["content"] == first["content"]


@pytest.mark.asyncio
async def test_cascade_pdf_empty(monkeypatch):
    async def fake_pdf(url):
        return "", 500, "boom"

    monkeypatch.setattr(fetch_mod, "_fetch_pdf", fake_pdf)
    result = await _cascade_pdf("https://example.com/x.pdf", "markdown", 8000)
    assert result["status"] == 500
    assert result["error"] == "boom"
