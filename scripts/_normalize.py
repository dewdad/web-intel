"""Unified output envelope for all web-intel commands."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_SLASH_RE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')


def normalize_date(raw: str) -> str:
    """
    Accept ISO 8601, RFC 2822, partial dates, or common formats.
    Return YYYY-MM-DD or "" for unparseable / relative strings.

    Examples:
        "2025-03-12T10:30:00Z"  -> "2025-03-12"
        "March 12, 2025"        -> "2025-03-12"
        "3 months ago"          -> ""   (relative — discard)
        "2025-03"               -> "2025-03"  (partial OK)
        ""                      -> ""
    """
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()

    # Already clean ISO prefix
    m = _ISO_RE.search(raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # MM/DD/YYYY
    m = _SLASH_RE.search(raw)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"

    # Try email/HTTP date formats via email.utils
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    # Try locale month names ("March 12, 2025", "12 March 2025")
    try:
        from datetime import datetime
        for fmt in ("%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d %b %Y"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    except Exception:
        pass

    # Relative strings ("3 months ago", "yesterday") — discard
    return ""


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def extract_domain(url: str) -> str:
    """Extract bare domain from URL, stripping www. prefix."""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


@dataclass
class WebResult:
    url: str = ""
    canonical_url: str = ""
    title: str = ""
    site_name: str = ""
    published_at: str = ""
    authors: list[str] = field(default_factory=list)
    language: str = ""
    content_type: str = "unknown"
    summary: str = ""
    markdown: str = ""
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    source_engine: str = ""
    fetch_mode: str = ""
    extract_mode: str = ""
    confidence: float = 0.0
    timing_ms: int = 0
    status: str = "ok"
    command: str = ""
    error: Optional[str] = None
    html: str = ""
    char_count: int = 0
    truncated: bool = False
    chunk_index: int = 0
    chunk_count: int = 0
    chunk_tokens: int = 0
    current_hash: str = ""
    previous_hash: str = ""
    changed: Optional[bool] = None
    citation: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("html", None)
        if d.get("changed") is None:
            d.pop("changed", None)
        if d.get("citation") is None:
            d.pop("citation", None)
        d = {
            k: v
            for k, v in d.items()
            if v or v == 0 or isinstance(v, (bool, int, float))
        }
        if "status" not in d:
            d["status"] = "ok"
        if "command" not in d:
            d["command"] = ""
        return d


@dataclass
class SearchResult:
    query: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    total_results: int = 0
    number_of_results: int = 0
    timing_ms: int = 0
    status: str = "ok"
    command: str = "search"
    error: Optional[str] = None
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("error"):
            d.pop("error", None)
        if not d.get("citations"):
            d.pop("citations", None)
        return d


@dataclass
class DiscoverResult:
    base_url: str = ""
    mode: str = "sitemap"
    urls: list[str] = field(default_factory=list)
    url_entries: list[dict] = field(default_factory=list)
    total_urls: int = 0
    timing_ms: int = 0
    status: str = "ok"
    command: str = "discover"
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("error"):
            d.pop("error", None)
        return d


class Timer:
    """Context manager to measure elapsed time in milliseconds."""

    def __init__(self) -> None:
        self._start: float = 0
        self.elapsed_ms: int = 0

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = int((time.monotonic() - self._start) * 1000)


def emit(data: dict[str, Any] | list[dict[str, Any]], *, pretty: bool = False) -> None:
    """Write JSON to stdout. All output goes through this single function."""
    indent = 2 if pretty else None
    json.dump(data, sys.stdout, indent=indent, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_error(command: str, error: str, *, pretty: bool = False) -> None:
    """Emit a standardized error envelope."""
    emit({"status": "failed", "command": command, "error": error}, pretty=pretty)
