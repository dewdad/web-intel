"""Unified output envelope for all web-intel commands."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class WebResult:
    """Single-page result envelope."""

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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
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
    """Search results envelope."""

    query: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    total_results: int = 0
    timing_ms: int = 0
    status: str = "ok"
    command: str = "search"
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("error"):
            d.pop("error", None)
        return d


@dataclass
class DiscoverResult:
    """Site discovery envelope."""

    base_url: str = ""
    mode: str = "sitemap"
    urls: list[str] = field(default_factory=list)
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
