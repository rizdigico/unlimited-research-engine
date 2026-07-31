from research.report import build_report


def test_build_report_structure():
    urls = [
        {"rank": 1, "href": "https://a.com", "title": "A", "body": "snippet a", "source": "searxng"},
        {"rank": 2, "href": "https://b.com", "title": "B", "body": "snippet b", "source": "ddgs"},
    ]
    scraped = [
        {"status": 200, "method": "scrapling", "cached": False, "content_length": 100, "content": "content a", "error": None},
        {"status": 0, "method": "none", "cached": False, "content_length": 0, "content": "", "error": "empty content"},
    ]
    report = build_report("query here", urls, scraped, ["searxng", "ddgs"])
    assert report["query"] == "query here"
    assert report["sources_used"] == ["searxng", "ddgs"]
    assert report["num_results"] == 2
    assert report["sources"][0]["url"] == "https://a.com"
    assert report["sources"][0]["status"] == 200
    assert report["sources"][1]["error"] == "empty content"


def test_build_report_tolerates_mismatched_lengths():
    urls = [{"rank": 1, "href": "https://a.com", "title": "A", "body": "", "source": "searxng"}]
    report = build_report("q", urls, [], [])
    assert report["sources"][0]["status"] == 0
