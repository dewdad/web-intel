from __future__ import annotations

import re
from typing import Optional

from _config import get_logger
from _normalize import WebResult, DiscoverResult, Timer, normalize_date

log = get_logger("trafilatura")


def _markdown_to_text(md: str) -> str:
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', md)
    text = re.sub(r'[#*_`~>|]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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
    import trafilatura

    html_len = len(html)
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
                output_format="markdown",
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

    if not extracted:
        return WebResult(
            url=url,
            status="partial",
            extract_mode="trafilatura",
            confidence=0.0,
            error="Trafilatura returned empty content — page may require JavaScript",
            timing_ms=t.elapsed_ms,
        )

    markdown_content = extracted if output_format == "markdown" else ""
    text_content = _markdown_to_text(extracted) if extracted else ""
    extracted_len = len(extracted)
    confidence = min((extracted_len / max(html_len, 1)) * 5, 1.0) if extracted_len else 0.0

    return WebResult(
        url=url,
        canonical_url=meta.get("canonical_url", ""),
        title=meta.get("title", ""),
        site_name=meta.get("sitename", ""),
        published_at=meta.get("date", ""),
        authors=meta.get("authors", []),
        language=meta.get("language", ""),
        markdown=markdown_content or text_content,
        text=text_content,
        extract_mode="trafilatura",
        confidence=confidence,
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
            "date": normalize_date(meta.date or ""),
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


def discover_sitemap_enriched(url: str, *, max_urls: int = 100) -> DiscoverResult:
    import httpx
    import xml.etree.ElementTree as ET
    from urllib.parse import urljoin

    candidates = [
        urljoin(url, "/sitemap.xml"),
        urljoin(url, "/sitemap_index.xml"),
        urljoin(url, "/sitemap.gz"),
    ]
    entries = []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    for sitemap_url in candidates:
        try:
            resp = httpx.get(sitemap_url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for url_el in root.findall(".//sm:url", ns)[:max_urls]:
                loc = url_el.findtext("sm:loc", namespaces=ns) or ""
                if not loc:
                    continue
                entry: dict = {"url": loc}
                for f in ("lastmod", "changefreq", "priority"):
                    val = url_el.findtext(f"sm:{f}", namespaces=ns)
                    if val:
                        entry[f] = val
                entries.append(entry)
            if entries:
                break
        except Exception:
            continue

    return DiscoverResult(
        base_url=url,
        mode="sitemap",
        urls=[e["url"] for e in entries],
        url_entries=entries,
        total_urls=len(entries),
    )


def discover_crawl(
    url: str,
    *,
    max_urls: int = 100,
    language: Optional[str] = None,
) -> DiscoverResult:
    from _httpx_fetch import fetch
    from urllib.parse import urljoin, urlparse

    base_domain = urlparse(url).netloc
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(url, 0)]
    entries: list[dict] = []

    with Timer() as t:
        while queue and len(entries) < max_urls:
            current_url, depth = queue.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)

            try:
                html, _, _ = fetch(current_url, timeout=10)
            except Exception:
                continue

            hrefs: list[str] = []
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                hrefs = [
                    urljoin(current_url, a.get("href", ""))
                    for a in soup.find_all("a", href=True)
                ]
            except Exception:
                pass

            entries.append({"url": current_url, "depth": depth})

            for href in hrefs:
                parsed = urlparse(href)
                if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                    if href not in visited:
                        queue.append((href, depth + 1))

    return DiscoverResult(
        base_url=url,
        mode="crawl",
        urls=[e["url"] for e in entries],
        url_entries=entries,
        total_urls=len(entries),
        timing_ms=t.elapsed_ms,
    )
