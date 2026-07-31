"""Content extraction.

Order of preference:

1. **trafilatura** — the best open-source readability extractor. Pulls the main
   article/body text (tables kept), returns clean markdown or plain text, and
   also exposes metadata (title, description, site name, byline, language).
2. **markdownify** — HTML → markdown fallback when trafilatura is unavailable
   or returns nothing (works on any well-formed HTML).
3. **pypdf** — PDF bytes → text for ``.pdf`` links.

Every function is defensive: a failure in one path silently falls through to
the next rather than aborting a scrape.
"""

from __future__ import annotations

import re
from typing import Any

from .logging_utils import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - import guard
    import trafilatura
    TRAFILATURA_AVAILABLE = True
    TRAFILATURA_ERROR = None
except Exception as exc:  # pragma: no cover
    trafilatura = None
    TRAFILATURA_AVAILABLE = False
    TRAFILATURA_ERROR = str(exc)

try:  # pragma: no cover - import guard
    from markdownify import markdownify as _markdownify
    MARKDOWNIFY_AVAILABLE = True
    MARKDOWNIFY_ERROR = None
except Exception as exc:  # pragma: no cover
    _markdownify = None
    MARKDOWNIFY_AVAILABLE = False
    MARKDOWNIFY_ERROR = str(exc)

try:  # pragma: no cover - import guard
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
    PYPDF_ERROR = None
except Exception as exc:  # pragma: no cover
    PdfReader = None
    PYPDF_AVAILABLE = False
    PYPDF_ERROR = str(exc)

_MD_NOISE = re.compile(r"^[#>*_`~\-]{1,6}\s*", re.MULTILINE)


def extract_content(html: str, fmt: str = "markdown", url: str = "") -> str:
    """Extract the main readable content from an HTML string."""
    if not html or not html.strip():
        return ""

    if TRAFILATURA_AVAILABLE:
        try:
            target_format = "markdown" if fmt == "markdown" else "txt"
            text = trafilatura.extract(
                html,
                output_format=target_format,
                include_comments=False,
                include_tables=True,
                url=url or None,
            )
            if text and len(text.strip()) > 0:
                return text.strip()
        except Exception as exc:
            logger.debug("trafilatura extraction failed: %s", exc)

    if MARKDOWNIFY_AVAILABLE:
        try:
            md = _markdownify(
                html,
                heading_style="ATX",
                strip=["script", "style", "nav", "footer", "header", "aside", "form"],
            )
            md = re.sub(r"\n{3,}", "\n\n", md)
            if fmt == "text":
                md = _MD_NOISE.sub("", md)
            return md.strip()
        except Exception as exc:
            logger.debug("markdownify extraction failed: %s", exc)

    return ""


def extract_metadata(html: str) -> dict[str, Any]:
    """Best-effort metadata (title, description, site name, language)."""
    meta: dict[str, Any] = {}
    if TRAFILATURA_AVAILABLE and html:
        try:
            md = trafilatura.extract_metadata(html)
            if md:
                meta = {
                    "title": md.title,
                    "author": getattr(md, "author", None),
                    "description": getattr(md, "description", None),
                    "sitename": getattr(md, "sitename", None),
                    "language": getattr(md, "language", None),
                }
        except Exception:
            pass
    if not meta.get("title") and html:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if match:
            meta["title"] = re.sub(r"\s+", " ", match.group(1)).strip()
    return {k: v for k, v in meta.items() if v}


def extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes via pypdf."""
    if not PYPDF_AVAILABLE:
        raise RuntimeError(f"pypdf not available: {PYPDF_ERROR}")
    import io

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
        except Exception:
            continue
    return "\n\n".join(parts)


def truncate(text: str, max_len: int) -> str:
    if max_len <= 0:
        return text
    return text[:max_len]
