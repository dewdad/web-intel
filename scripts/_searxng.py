from __future__ import annotations

from typing import Any

from _config import SEARXNG_URL, SEARXNG_API_KEY, create_httpx_client, get_logger
from _normalize import SearchResult, Timer

log = get_logger("searxng")


def search(
    query: str,
    *,
    engines: str = "",
    categories: str = "general",
    language: str = "en",
    time_range: str = "",
    max_results: int = 10,
    pageno: int = 1,
) -> SearchResult:
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": language,
        "pageno": pageno,
    }
    if engines:
        params["engines"] = engines
    if time_range:
        params["time_range"] = time_range

    headers: dict[str, str] = {}
    if SEARXNG_API_KEY:
        headers["Authorization"] = f"Bearer {SEARXNG_API_KEY}"

    with Timer() as t:
        try:
            with create_httpx_client(timeout=15) as client:
                resp = client.get(
                    f"{SEARXNG_URL}/search", params=params, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.error("SearXNG request failed: %s", exc)
            return SearchResult(
                query=query,
                status="failed",
                error=f"SearXNG request failed: {exc}. Is SearXNG running at {SEARXNG_URL}?",
                timing_ms=t.elapsed_ms,
            )

    raw_results = data.get("results", [])[:max_results]
    mapped = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("content", ""),
            "engine": r.get("engine", ""),
            "score": r.get("score", 0),
        }
        for r in raw_results
    ]

    return SearchResult(
        query=query,
        results=mapped,
        total_results=len(mapped),
        timing_ms=t.elapsed_ms,
    )
