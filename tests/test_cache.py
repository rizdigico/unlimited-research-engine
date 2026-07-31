import pytest

from research.cache import DiskCache


@pytest.fixture
def cache(tmp_path):
    return DiskCache("test", root=tmp_path, ttl=60)


def test_set_and_get_roundtrip(cache):
    cache.set("hello", {"url": "https://example.com", "content": "x" * 100})
    got = cache.get("hello")
    assert got == {"url": "https://example.com", "content": "x" * 100}


def test_missing_key_returns_none(cache):
    assert cache.get("nope") is None


def test_ttl_expiry(tmp_path):
    cache = DiskCache("test", root=tmp_path, ttl=-1)
    cache.set("k", {"v": 1})
    assert cache.get("k") is None


def test_delete(cache):
    cache.set("k", {"v": 1})
    cache.delete("k")
    assert cache.get("k") is None


def test_stats(cache):
    assert cache.stats()["entries"] == 0
    cache.set("a", {"v": 1})
    cache.set("b", {"v": 2})
    stats = cache.stats()
    assert stats["entries"] == 2
    assert stats["size_bytes"] > 0


def test_non_dict_data_returns_none(cache):
    cache.root.mkdir(parents=True, exist_ok=True)
    import json

    (cache.root / f"{cache._key('k')}.json").write_text(json.dumps({"ts": 1, "data": "not a dict"}), encoding="utf-8")
    assert cache.get("k") is None
