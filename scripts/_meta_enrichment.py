"""
Metadata enrichment: fetch page <head> and extract missing published_at / authors.

Used when search results or fetched pages have empty published_at or authors.
Fetches only the first 16KB using stream truncation (Range only when server
advertises Accept-Ranges: bytes). No new dependencies — uses httpx + bs4 (already
in CORE_DEPS).

Optimizations applied:
- HEAD probe skips non-HTML content types (PDFs, feeds, etc.)
- Range header used only when server sends Accept-Ranges: bytes
- Stream-truncation stops reading after _HEAD_BYTES — no full body download
- BeautifulSoup parsed exactly once per URL; soup passed to all strategy functions
- ThreadPoolExecutor (not asyncio.run) — safe to call from any calling context
- Early return from each strategy tier as soon as both fields are satisfied
"""
from __future__ import annotations

import concurrent.futures
import json
from dataclasses import dataclass, field
from typing import Optional

from _config import create_httpx_client, get_logger
from _normalize import normalize_date, Timer

log = get_logger("meta_enrichment")

_HEAD_BYTES = 16_384


@dataclass
class EnrichmentResult:
    url: str = ""
    published_at: str = ""
    authors: list[str] = field(default_factory=list)
    enriched_fields: list[str] = field(default_factory=list)
    timing_ms: int = 0
    source: str = ""
    error: Optional[str] = None


def enrich_metadata(
    url: str,
    *,
    need_date: bool = True,
    need_authors: bool = True,
    timeout: int = 8,
) -> EnrichmentResult:
    if not need_date and not need_authors:
        return EnrichmentResult(url=url)

    with Timer() as t:
        try:
            html_head = _fetch_head(url, timeout=timeout)
        except Exception as exc:
            return EnrichmentResult(url=url, error=str(exc), timing_ms=t.elapsed_ms)

        if not html_head:
            return EnrichmentResult(url=url, error="empty response", timing_ms=t.elapsed_ms)

        result = EnrichmentResult(url=url)

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_head, "lxml")

        def _satisfied() -> bool:
            return (not need_date or bool(result.published_at)) and \
                   (not need_authors or bool(result.authors))

        _try_json_ld(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        _try_opengraph(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        _try_meta_tags(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        _try_semantic_html(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        _try_trafilatura(html_head, url, result, need_date=need_date, need_authors=need_authors)

        result.timing_ms = t.elapsed_ms
    return result


def _fetch_head(url: str, timeout: int) -> str:
    with create_httpx_client(timeout=timeout) as client:
        accepts_range = False
        try:
            head_resp = client.head(url)
            content_type = head_resp.headers.get("content-type", "").lower()
            if "html" not in content_type:
                log.debug("Skipping non-HTML URL %s (content-type: %s)", url, content_type)
                return ""
            accepts_range = head_resp.headers.get("accept-ranges", "").lower() == "bytes"
        except Exception:
            pass

        if accepts_range:
            try:
                resp = client.get(url, headers={"Range": f"bytes=0-{_HEAD_BYTES - 1}"})
                if resp.status_code in (200, 206):
                    return resp.text[:_HEAD_BYTES]
            except Exception:
                pass

        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes(chunk_size=4096):
                chunks.append(chunk)
                total += len(chunk)
                if total >= _HEAD_BYTES:
                    break
            return b"".join(chunks)[:_HEAD_BYTES].decode("utf-8", errors="replace")


_JSONLD_DATE_FIELDS = ("datePublished", "dateCreated", "dateModified")
_JSONLD_TYPES = ("Article", "NewsArticle", "BlogPosting", "WebPage", "TechArticle", "ScholarlyArticle")


def _try_json_ld(
    soup: "BeautifulSoup",
    result: EnrichmentResult,
    *,
    need_date: bool,
    need_authors: bool,
) -> None:
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            items = (
                data.get("@graph", [data]) if isinstance(data, dict)
                else data if isinstance(data, list)
                else [data]
            )
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type", "")
                if isinstance(item_type, list):
                    item_type = item_type[0] if item_type else ""
                if not any(t in str(item_type) for t in _JSONLD_TYPES):
                    continue

                if need_date and not result.published_at:
                    for field_name in _JSONLD_DATE_FIELDS:
                        raw = item.get(field_name, "")
                        if raw:
                            normed = normalize_date(str(raw))
                            if normed:
                                result.published_at = normed
                                result.enriched_fields.append("published_at")
                                result.source = result.source or "json-ld"
                                break

                if need_authors and not result.authors:
                    author_data = item.get("author", [])
                    if isinstance(author_data, dict):
                        author_data = [author_data]
                    elif isinstance(author_data, str):
                        author_data = [{"name": author_data}]
                    names = [
                        a.get("name", "").strip()
                        for a in author_data
                        if isinstance(a, dict) and a.get("name")
                    ]
                    if names:
                        result.authors = [n for n in names if n]
                        result.enriched_fields.append("authors")
                        result.source = result.source or "json-ld"

                if (not need_date or result.published_at) and (not need_authors or result.authors):
                    return

    except Exception as exc:
        log.debug("JSON-LD extraction failed: %s", exc)


_OG_DATE_PROPS = frozenset((
    "article:published_time",
    "og:article:published_time",
    "article:modified_time",
    "og:published_time",
    "og:updated_time",
))
_OG_AUTHOR_PROPS = frozenset((
    "article:author",
    "og:article:author",
))


def _try_opengraph(
    soup: "BeautifulSoup",
    result: EnrichmentResult,
    *,
    need_date: bool,
    need_authors: bool,
) -> None:
    try:
        for tag in soup.find_all("meta"):
            prop = tag.get("property", "").lower()
            content = (tag.get("content") or "").strip()
            if not content:
                continue

            if need_date and not result.published_at and prop in _OG_DATE_PROPS:
                normed = normalize_date(content)
                if normed:
                    result.published_at = normed
                    result.enriched_fields.append("published_at")
                    result.source = result.source or "opengraph"

            if need_authors and not result.authors and prop in _OG_AUTHOR_PROPS:
                if not content.startswith("http"):
                    result.authors = [content]
                    result.enriched_fields.append("authors")
                    result.source = result.source or "opengraph"

            if (not need_date or result.published_at) and (not need_authors or result.authors):
                return

    except Exception as exc:
        log.debug("OpenGraph extraction failed: %s", exc)


_META_DATE_NAMES = frozenset((
    "date",
    "dc.date",
    "dc.date.issued",
    "dcterms.date",
    "dcterms.created",
    "parsely-pub-date",
    "sailthru.date",
    "cxenseparse:recs:publishtime",
    "article.published",
    "published_time",
    "last-modified",
))
_META_AUTHOR_NAMES = frozenset((
    "author",
    "dc.creator",
    "dcterms.creator",
    "parsely-author",
    "sailthru.author",
    "article.author",
    "byl",
))


def _try_meta_tags(
    soup: "BeautifulSoup",
    result: EnrichmentResult,
    *,
    need_date: bool,
    need_authors: bool,
) -> None:
    try:
        for tag in soup.find_all("meta"):
            name = (tag.get("name") or tag.get("itemprop") or "").lower()
            content = (tag.get("content") or "").strip()
            if not content:
                continue

            if need_date and not result.published_at and name in _META_DATE_NAMES:
                normed = normalize_date(content)
                if normed:
                    result.published_at = normed
                    result.enriched_fields.append("published_at")
                    result.source = result.source or "meta"

            if need_authors and not result.authors and name in _META_AUTHOR_NAMES:
                authors = [a.strip() for a in content.split(";") if a.strip()]
                if authors:
                    result.authors = authors
                    result.enriched_fields.append("authors")
                    result.source = result.source or "meta"

            if (not need_date or result.published_at) and (not need_authors or result.authors):
                return

    except Exception as exc:
        log.debug("Meta tag extraction failed: %s", exc)


def _try_semantic_html(
    soup: "BeautifulSoup",
    result: EnrichmentResult,
    *,
    need_date: bool,
    need_authors: bool,
) -> None:
    try:
        if need_date and not result.published_at:
            for time_el in soup.find_all("time"):
                datetime_attr = (time_el.get("datetime") or "").strip()
                itemprop = (time_el.get("itemprop") or "").lower()
                if datetime_attr and (
                    "publish" in itemprop or time_el.get("pubdate") is not None
                ):
                    normed = normalize_date(datetime_attr)
                    if normed:
                        result.published_at = normed
                        result.enriched_fields.append("published_at")
                        result.source = result.source or "semantic-html"
                        break

        if need_authors and not result.authors:
            for a_el in soup.find_all("a", rel=True):
                if "author" in (a_el.get("rel") or []):
                    name = a_el.get_text(strip=True)
                    if name:
                        result.authors = [name]
                        result.enriched_fields.append("authors")
                        result.source = result.source or "semantic-html"
                        break

    except Exception as exc:
        log.debug("Semantic HTML extraction failed: %s", exc)


def _try_trafilatura(
    html: str,
    url: str,
    result: EnrichmentResult,
    *,
    need_date: bool,
    need_authors: bool,
) -> None:
    try:
        from trafilatura.metadata import extract_metadata
        meta = extract_metadata(html, default_url=url)
        if meta is None:
            return
        if need_date and not result.published_at and meta.date:
            normed = normalize_date(meta.date)
            if normed:
                result.published_at = normed
                result.enriched_fields.append("published_at")
                result.source = result.source or "trafilatura"
        if need_authors and not result.authors and meta.author:
            authors = [a.strip() for a in meta.author.split(";") if a.strip()]
            if authors:
                result.authors = authors
                result.enriched_fields.append("authors")
                result.source = result.source or "trafilatura"
    except Exception as exc:
        log.debug("Trafilatura metadata fallback failed: %s", exc)


def enrich_search_results(
    results: list[dict],
    *,
    concurrency: int = 5,
    timeout: int = 8,
) -> list[dict]:
    to_enrich = [
        (i, r) for i, r in enumerate(results)
        if not r.get("published_at") or not r.get("authors")
    ]
    if not to_enrich:
        return results

    def _do_one(item: tuple[int, dict]) -> None:
        idx, r = item
        url = r.get("url", "")
        if not url:
            return
        enriched = enrich_metadata(
            url,
            need_date=not bool(r.get("published_at")),
            need_authors=not bool(r.get("authors")),
            timeout=timeout,
        )
        if enriched.published_at:
            results[idx]["published_at"] = enriched.published_at
        if enriched.authors:
            results[idx]["authors"] = enriched.authors
        if enriched.enriched_fields:
            results[idx]["meta_enriched"] = enriched.enriched_fields
            results[idx]["meta_source"] = enriched.source

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(_do_one, to_enrich))

    return results
