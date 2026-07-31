import pytest

from research import deep_research, engine_status, scrape_url, search_urls

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_search_urls_live():
    result = await search_urls("python asyncio best practices", num_results=5, time_range="")
    assert result["results"], "expected at least one URL"
    assert result["sources_used"], "expected at least one search source"


@pytest.mark.asyncio
async def test_scrape_url_live_html():
    result = await scrape_url("https://example.com", "markdown", 4000, "auto")
    assert result["status"] == 200
    assert result["content"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_scrape_url_live_js_page():
    result = await scrape_url("https://news.ycombinator.com", "markdown", 4000, "auto")
    assert result["status"] == 200
    assert len(result["content"]) > 100


@pytest.mark.asyncio
async def test_deep_research_live():
    result = await deep_research("open source web scraping python 2026", num_results=3, max_content_length=1500, time_range="")
    assert result["num_results"] >= 1
    first = result["sources"][0]
    assert first["url"]
    assert first["content"] or first["error"]  # content or a reported upstream error


@pytest.mark.asyncio
async def test_engine_status_live():
    status = await engine_status()
    assert status["engine"] == "unlimited-research"
    assert status["config"]["searxng_reachable"] is True
    assert status["availability"]["scrapling"] is True
    assert status["availability"]["crawl4ai"] is True
