from __future__ import annotations

from typing import Optional

from _config import get_logger
from _normalize import WebResult, DiscoverResult, Timer

log = get_logger("trafilatura")


def extract_from_html(
    html: str,
    *,
    url: str = "",
    include_tables: bool = False,
    include_links: bool = False,
    include_images: bool = False,
    include_comments: bool = False,
    favor_precision: bool = False,
    favor_recall: bool = False,
    deduplicate: bool = True,
    output_format: str = "markdown",
) -> WebResult:
    """Extract content from HTML string using Trafilatura."""
    import trafilatura

    with Timer() as t:
        try:
            extracted = trafilatura.extract(
                html,
                url=url or None,
                include_tables=include_tables,
                include_links=include_links,
                include_images=include_images,
                include_comments=include_comments,
                favor_precision=favor_precision,
                favor_recall=favor_recall,
                deduplicate=deduplicate,
                output_format="txt",
            )

            markdown_content = ""
            if output_format == "markdown":
                markdown_content = (
                    trafilatura.extract(
                        html,
                        url=url or None,
                        include_tables=include_tables,
                        include_links=include_links,
                        include_images=include_images,
                        include_comments=include_comments,
                        favor_precision=favor_precision,
                        favor_recall=favor_recall,
                        deduplicate=deduplicate,
                        output_format="markdown",
                    )
                    or ""
                )

            metadata = trafilatura.extract(
                html,
                url=url or None,
                output_format="xmltei",
                with_metadata=True,
                only_with_metadata=False,
            )
            meta = _parse_metadata(html, url)

        except Exception as exc:
            log.error("Trafilatura extraction failed: %s", exc)
            return WebResult(
                url=url,
                status="failed",
                extract_mode="trafilatura",
                error=f"Extraction failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    if not extracted and not markdown_content:
        return WebResult(
            url=url,
            status="partial",
            extract_mode="trafilatura",
            confidence=0.0,
            error="Trafilatura returned empty content — page may require JavaScript",
            timing_ms=t.elapsed_ms,
        )

    return WebResult(
        url=url,
        canonical_url=meta.get("canonical_url", ""),
        title=meta.get("title", ""),
        site_name=meta.get("sitename", ""),
        published_at=meta.get("date", ""),
        authors=meta.get("authors", []),
        language=meta.get("language", ""),
        markdown=markdown_content or extracted or "",
        text=extracted or "",
        extract_mode="trafilatura",
        confidence=0.85 if extracted else 0.0,
        timing_ms=t.elapsed_ms,
    )


def _parse_metadata(html: str, url: str) -> dict:
    try:
        from trafilatura.metadata import extract_metadata

        meta = extract_metadata(html, default_url=url)
        if meta is None:
            return {}
        return {
            "title": meta.title or "",
            "canonical_url": meta.url or "",
            "sitename": meta.sitename or "",
            "date": meta.date or "",
            "authors": [a for a in (meta.author or "").split(";") if a.strip()],
            "language": meta.pagetype or "",
        }
    except Exception:
        return {}


def fetch_and_extract(
    url: str,
    *,
    include_tables: bool = False,
    include_links: bool = False,
    include_images: bool = False,
    include_comments: bool = False,
    favor_precision: bool = False,
    favor_recall: bool = False,
    output_format: str = "markdown",
    timeout: Optional[int] = None,
) -> WebResult:
    """Fetch URL via httpx then extract with Trafilatura. Primary fast-path."""
    from _httpx_fetch import fetch

    with Timer() as t:
        try:
            html, status_code, _ = fetch(url, timeout=timeout)
        except Exception as exc:
            log.error("Fetch failed for %s: %s", url, exc)
            return WebResult(
                url=url,
                status="failed",
                fetch_mode="httpx",
                extract_mode="trafilatura",
                error=f"Fetch failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    result = extract_from_html(
        html,
        url=url,
        include_tables=include_tables,
        include_links=include_links,
        include_images=include_images,
        include_comments=include_comments,
        favor_precision=favor_precision,
        favor_recall=favor_recall,
        output_format=output_format,
    )
    result.fetch_mode = "httpx"
    result.timing_ms = t.elapsed_ms
    return result


def discover_sitemap(
    url: str,
    *,
    target_lang: Optional[str] = None,
    max_urls: int = 100,
) -> DiscoverResult:
    from trafilatura.sitemaps import sitemap_search

    with Timer() as t:
        try:
            urls = sitemap_search(url, target_lang=target_lang) or []
            urls = urls[:max_urls]
        except Exception as exc:
            log.error("Sitemap discovery failed for %s: %s", url, exc)
            return DiscoverResult(
                base_url=url,
                mode="sitemap",
                status="failed",
                error=f"Sitemap discovery failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    return DiscoverResult(
        base_url=url,
        mode="sitemap",
        urls=urls,
        total_urls=len(urls),
        timing_ms=t.elapsed_ms,
    )


def discover_crawl(
    url: str,
    *,
    max_urls: int = 100,
    language: Optional[str] = None,
) -> DiscoverResult:
    from trafilatura.spider import focused_crawler

    with Timer() as t:
        try:
            known, _visited = focused_crawler(
                url,
                max_seen_urls=max_urls,
                max_known_urls=max_urls * 5,
                lang=language,
            )
            urls = (known or [])[:max_urls]
        except Exception as exc:
            log.error("Focused crawl failed for %s: %s", url, exc)
            return DiscoverResult(
                base_url=url,
                mode="crawl",
                status="failed",
                error=f"Focused crawl failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    return DiscoverResult(
        base_url=url,
        mode="crawl",
        urls=urls,
        total_urls=len(urls),
        timing_ms=t.elapsed_ms,
    )
