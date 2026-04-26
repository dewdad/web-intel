from __future__ import annotations

from _config import create_httpx_client, get_logger
from _normalize import SearchResult, Timer, normalize_date, extract_domain

log = get_logger("search_fallback")


def search_ddgs(
    query: str,
    *,
    max_results: int = 10,
    timeout: int = 15,
) -> SearchResult:
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException

    with Timer() as t:
        try:
            raw = DDGS(timeout=timeout).text(query, max_results=max_results, backend="auto")
        except RatelimitException as exc:
            return SearchResult(
                query=query, status="failed",
                error=f"ddgs rate limited: {exc}", timing_ms=t.elapsed_ms,
                backend="ddgs",
            )
        except Exception as exc:
            return SearchResult(
                query=query, status="failed",
                error=f"ddgs fallback failed: {exc}", timing_ms=t.elapsed_ms,
                backend="ddgs",
            )

    if not raw:
        return SearchResult(
            query=query, status="partial",
            error="ddgs returned no results", timing_ms=t.elapsed_ms,
            backend="ddgs",
        )

    results = [
        {
            "url": r.get("href", ""),
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "engine": "ddgs",
            "engines": ["ddgs"],
            "score": 0,
            "domain": extract_domain(r.get("href", "")),
            "published_at": "",
            "category": "",
            "quality_score": 0.0,
        }
        for r in raw
        if r.get("href")
    ]
    return SearchResult(
        query=query, results=results,
        total_results=len(results), timing_ms=t.elapsed_ms,
        backend="ddgs",
    )


def search_brave(
    query: str,
    *,
    api_key: str,
    max_results: int = 10,
    timeout: int = 10,
) -> SearchResult:
    with Timer() as t:
        try:
            with create_httpx_client(timeout=timeout) as client:
                resp = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": max_results},
                    headers={"Accept": "application/json",
                             "Accept-Encoding": "gzip",
                             "X-Subscription-Token": api_key},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return SearchResult(query=query, status="failed",
                                error=f"Brave Search API failed: {exc}", timing_ms=t.elapsed_ms,
                                backend="brave")

    web_results = data.get("web", {}).get("results", [])[:max_results]
    results = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("description", ""),
            "engine": "brave",
            "engines": ["brave"],
            "score": r.get("relevance_score", 0),
            "domain": extract_domain(r.get("url", "")),
            "published_at": normalize_date(r.get("page_age", "")),
            "category": "",
            "quality_score": 0.0,
        }
        for r in web_results
    ]
    return SearchResult(query=query, results=results, total_results=len(results), timing_ms=t.elapsed_ms,
                        backend="brave")
