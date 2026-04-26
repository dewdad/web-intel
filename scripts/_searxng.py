from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlparse

from _config import SEARXNG_URL, SEARXNG_API_KEY, create_httpx_client, get_logger
from _normalize import SearchResult, Timer

log = get_logger("searxng")


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _compute_quality_score(result: dict, query: str) -> float:
    query_terms = set(re.findall(r'\b[a-z]{2,}\b', query.lower()))
    if not query_terms:
        return 0.0

    content = (result.get("title", "") + " " + result.get("snippet", "")).lower()
    content_terms = set(re.findall(r'\b[a-z]{2,}\b', content))
    overlap = len(query_terms & content_terms) / len(query_terms)
    overlap_score = min(overlap * 0.5, 0.5)

    engine_count = len(result.get("engines", [result.get("engine", "")]))
    engine_score = min((engine_count - 1) * 0.1, 0.3)

    raw_score = result.get("score", 0)
    score_norm = min(raw_score / 3.0 * 0.2, 0.2)

    return round(overlap_score + engine_score + score_norm, 3)


def search(
    query: str,
    *,
    engines: str = "",
    categories: str = "general",
    language: str = "en",
    time_range: str = "",
    max_results: int = 10,
    pageno: int = 1,
    no_rerank: bool = False,
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

    raw_results = data.get("results", [])
    number_of_results = data.get("number_of_results", 0)

    mapped = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("content", ""),
            "engine": r.get("engine", ""),
            "engines": r.get("engines", []),
            "score": r.get("score", 0),
            "domain": _extract_domain(r.get("url", "")),
            "published_at": r.get("publishedDate", "") or r.get("published_date", ""),
            "category": r.get("category", ""),
        }
        for r in raw_results
    ]

    seen: dict[str, dict] = {}
    for r in mapped:
        url = r["url"]
        if url in seen:
            seen[url]["engines"] = list(set(seen[url]["engines"] + r["engines"]))
            seen[url]["score"] = max(seen[url]["score"], r["score"])
        else:
            seen[url] = r
    mapped = list(seen.values())[:max_results]

    for r in mapped:
        r["quality_score"] = _compute_quality_score(r, query)

    if not no_rerank:
        mapped.sort(key=lambda r: r["quality_score"], reverse=True)

    return SearchResult(
        query=query,
        results=mapped,
        total_results=len(mapped),
        number_of_results=number_of_results,
        timing_ms=t.elapsed_ms,
    )
