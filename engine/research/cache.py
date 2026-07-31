"""Thread-safe TTL disk cache used for search results and fetched pages.

Two instances live at module level:

- ``SEARCH_CACHE`` — dedupes identical queries so SearXNG/DDGS are not hammered.
- ``FETCH_CACHE`` — avoids re-downloading the same page within the TTL window.

Entries are JSON files keyed by a SHA-256 of the canonical key text, so cache
keys are deterministic and safe for filesystem use.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, FETCH_CACHE_TTL, MAX_CACHE_ENTRIES, SEARCH_CACHE_TTL


class DiskCache:
    def __init__(self, name: str = "cache", root: Path = CACHE_DIR, ttl: int = 600):
        self.root = root / name
        self.ttl = ttl
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key_text: str) -> dict[str, Any] | None:
        with self._lock:
            path = self._path(self._key(key_text))
            if not path.exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    entry = json.load(fh)
                if time.time() - entry.get("ts", 0) > self.ttl:
                    self.delete(key_text)
                    return None
                data = entry.get("data")
                return data if isinstance(data, dict) else None
            except Exception:
                return None

    def set(self, key_text: str, data: dict[str, Any], ttl: int | None = None) -> None:
        with self._lock:
            self._prune()
            path = self._path(self._key(key_text))
            entry = {"ts": time.time(), "data": data}
            tmp = path.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(entry, fh, ensure_ascii=False)
                os.replace(tmp, path)
            except Exception:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    def delete(self, key_text: str) -> None:
        with self._lock:
            try:
                self._path(self._key(key_text)).unlink(missing_ok=True)
            except Exception:
                pass

    def clear(self) -> None:
        with self._lock:
            try:
                for f in self.root.glob("*.json"):
                    f.unlink(missing_ok=True)
            except Exception:
                pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            files = list(self.root.glob("*.json"))
            ages: list[float] = []
            size = 0
            now = time.time()
            for f in files:
                try:
                    size += f.stat().st_size
                    ages.append(now - f.stat().st_mtime)
                except Exception:
                    pass
            return {
                "entries": len(files),
                "size_bytes": size,
                "oldest_age": max(ages, default=0),
                "newest_age": min(ages, default=0),
            }

    def _prune(self) -> None:
        try:
            files = sorted(
                self.root.glob("*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if len(files) > MAX_CACHE_ENTRIES:
                for f in files[MAX_CACHE_ENTRIES:]:
                    f.unlink(missing_ok=True)
        except Exception:
            pass


SEARCH_CACHE = DiskCache("search", ttl=SEARCH_CACHE_TTL)
FETCH_CACHE = DiskCache("fetch", ttl=FETCH_CACHE_TTL)
