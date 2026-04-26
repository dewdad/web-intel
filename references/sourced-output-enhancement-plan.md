# Sourced Output Enhancement Plan
**Date:** 2026-04-26  
**Revised:** 2026-04-26 — enrichment and citations are now **default-on**; `--no-enrich` / `--no-cite` opt out.  
**Status:** Ready for implementation  
**Scope:** Every `search` result must always include `published_at`, `authors`, `domain`, and a `citations[]` array. More data can then be fetched or queried by the agent from those sourced results.

---

## Design Constraint (revised)

> **Sourcing is mandatory, not optional.**  
> Every `search` invocation must return results with `published_at` and `authors` populated wherever they can be found, and must always emit a `citations[]` array. Agents depend on this data to decide what to fetch next. Opt-out flags (`--no-enrich`, `--no-cite`) are available for speed-sensitive pipelines, but the default path is fully sourced.

This inverts the previous opt-in model (`--enrich-meta`, `--cite`).  
The previous flags **become the default**; new escape hatches suppress them.

---

## 1. Problem Statement

Search and research output from web-intel is not reliably sourced. Specifically:

| Gap | Root Cause | Commands Affected |
|---|---|---|
| `published_at` is `""` for all ddgs results | ddgs `.text()` returns no date field whatsoever | `search` (ddgs fallback) |
| `published_at` is a raw relative string (e.g. `"3 months ago"`) for Brave | Brave `page_age` is human-readable, not ISO | `search` (Brave fallback) |
| SearXNG `publishedDate` populated for only ~30–50% of results | Engine-dependent; Google/Bing omit it frequently | `search` (SearXNG) |
| `authors` never appears in any search result | Not captured at search layer from any backend | all `search` results |
| `published_at` / `authors` missing in fetch results when page metadata is sparse | trafilatura `extract_metadata()` gives up on weak signals | `fetch`, `crawl`, `extract` |
| No citation array in output | No `citations[]`, no `citation_index` | all commands |
| `output-schema.md` example omits `published_at`, `domain`, `quality_score` | Docs lag code | documentation |

The fix has two layers, both now **on by default**:
1. **Normalization layer** — fix what we already receive (ISO date parsing, domain extraction). Zero latency.
2. **Enrichment layer** — for results still missing date/authors after normalization, fetch the page `<head>` (16KB) and extract from JSON-LD / Open Graph / meta tags. Runs concurrently. Default concurrency: 5.

---

## 2. Architecture of the Enrichment Layer

### New module: `scripts/_meta_enrichment.py`

A lightweight, zero-new-dependency lookup script. Called only when `published_at` or `authors` is missing. Uses existing `httpx` + `bs4` (already required deps) to fetch `<head>` only and parse a prioritized signal chain.

**Signal priority chain for `published_at`:**

```
1. JSON-LD: Article/NewsArticle/BlogPosting.datePublished
2. JSON-LD: Article/NewsArticle/BlogPosting.dateModified  (fallback)
3. Open Graph: <meta property="article:published_time">
4. Open Graph: <meta property="og:article:published_time">
5. Standard meta: <meta name="date">
6. Standard meta: <meta name="DC.date">
7. Standard meta: <meta name="parsely-pub-date">
8. Standard meta: <meta name="sailthru.date">
9. Standard meta: <meta name="cXenseParse:recs:publishtime">
10. <time datetime="..."> element with pubdate attribute or itemprop="datePublished"
11. trafilatura.metadata.extract_metadata() — catches anything missed above
```

**Signal priority chain for `authors`:**

```
1. JSON-LD: Article.author[].name  (array of Person/Organization)
2. Open Graph: <meta property="article:author">
3. Standard meta: <meta name="author">
4. Standard meta: <meta name="DC.creator">
5. Standard meta: <meta name="parsely-author">
6. rel="author" link or <a rel="author"> text
7. trafilatura.metadata.extract_metadata().author  (semicolon-delimited string)
```

**Fetch strategy:** HEAD request first to check `Content-Type`. If HTML, fetch only the first 16KB (enough for `<head>`) using `Range: bytes=0-16383` header where supported, falling back to full GET with stream truncation. This keeps enrichment fast (< 300ms typical) and avoids downloading full article bodies.

**Module API:**

```python
# scripts/_meta_enrichment.py

@dataclass
class EnrichmentResult:
    url: str
    published_at: str   # ISO YYYY-MM-DD or "" if not found
    authors: list[str]  # [] if not found
    enriched_fields: list[str]  # which fields were actually found: ["published_at", "authors"]
    timing_ms: int
    source: str         # "json-ld" | "opengraph" | "meta" | "trafilatura" | ""


def enrich_metadata(
    url: str,
    *,
    need_date: bool = True,
    need_authors: bool = True,
    timeout: int = 8,
) -> EnrichmentResult:
    """
    Fetch page head and extract missing publish date and/or authors.
    Returns EnrichmentResult with whatever was found.
    Only fetches if need_date or need_authors is True.
    """
```

### Integration points

Enrichment runs **by default on every `search` call**. It is suppressed only with `--no-enrich`. When `--fetch-top N` is also active, enrichment for those N results is satisfied for free from the already-fetched full content — no extra round-trip. Results that already have both `published_at` and `authors` are skipped entirely (zero cost).

**Default concurrency for enrichment fetches:** 5 (same as `MAX_CONCURRENT_FETCHES`). Can be overridden per-call via `--enrich-concurrency N`.

---

## 3. Normalization Fixes (no new deps, no latency)

These are independent of enrichment and should land first.

### 3.1 `normalize_date()` utility — `_normalize.py`

Add a shared date normalization function. Accepts any date string, returns `YYYY-MM-DD` or `""`.

```python
# scripts/_normalize.py

import re
from datetime import datetime, timezone

_ISO_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_SLASH_RE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')

def normalize_date(raw: str) -> str:
    """
    Accept ISO 8601, RFC 2822, partial dates, or common formats.
    Return YYYY-MM-DD or "" for unparseable/relative strings.
    
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
```

**Wire into:**
- `_searxng.py` line 96: `"published_at": normalize_date(r.get("publishedDate", "") or r.get("published_date", ""))`
- `_search_fallback.py` line 93: `"published_at": normalize_date(r.get("age") or r.get("page_age", ""))` (Brave)
- `_trafilatura_extract.py` line 82: `published_at=normalize_date(meta.get("date", ""))`

### 3.2 `_extract_domain()` shared util

Currently defined only in `_searxng.py`. Extract to `_normalize.py` or `_config.py` and import in fallback modules.

```python
# Add to _normalize.py
from urllib.parse import urlparse

def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""
```

**Wire into** `_search_fallback.py` both `search_ddgs()` and `search_brave()` — replace hardcoded `"domain": ""` with `"domain": extract_domain(r.get("href", "") or r.get("url", ""))`.

---

## 4. The Enrichment Module — Full Spec

### Optimization notes (applied throughout implementation below)

Five issues identified in the optimization audit are resolved in this spec:

| # | Issue | Resolution |
|---|---|---|
| O1 | `Range` header doesn't save bandwidth — servers ignore it and send full body | HEAD probe first; only use `Range` when server advertises `Accept-Ranges: bytes`; otherwise stream-truncate |
| O2 | Non-HTML URLs (PDFs, feeds) waste a full GET | HEAD probe checks `Content-Type`; returns `""` immediately if not HTML |
| O3 | `asyncio.run()` inside `enrich_search_results` conflicts with existing event loops | Replace with `ThreadPoolExecutor` — consistent with `_fetch_parallel()` pattern, no event-loop dependency |
| O4 | BeautifulSoup parsed 4× per URL (once per strategy tier) | Parse once in `enrich_metadata`, pass `soup` object to all strategy functions |
| O5 | No early-exit inside strategy loops when both fields found | Each strategy function returns as soon as both `published_at` and `authors` are satisfied |

### `scripts/_meta_enrichment.py` — complete implementation spec

```python
"""
Metadata enrichment: fetch page <head> and extract missing published_at / authors.

Used when search results or fetched pages have empty published_at or authors.
Fetches only the first 16KB using stream truncation (Range only when server advertises it).
No new dependencies — uses httpx + bs4 (already in CORE_DEPS).

Optimizations:
- HEAD probe skips non-HTML content types entirely (PDFs, feeds, etc.)
- Range header used only when server sends Accept-Ranges: bytes
- Stream-truncation stops reading after _HEAD_BYTES — no full body download
- BeautifulSoup parsed exactly once per URL; soup passed to all strategy functions
- ThreadPoolExecutor (not asyncio.run) — safe to call from any context
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

_HEAD_BYTES = 16_384  # 16KB — enough for <head> on all major sites


@dataclass
class EnrichmentResult:
    url: str = ""
    published_at: str = ""
    authors: list[str] = field(default_factory=list)
    enriched_fields: list[str] = field(default_factory=list)
    timing_ms: int = 0
    source: str = ""   # "json-ld" | "opengraph" | "meta" | "semantic-html" | "trafilatura" | ""
    error: Optional[str] = None


def enrich_metadata(
    url: str,
    *,
    need_date: bool = True,
    need_authors: bool = True,
    timeout: int = 8,
) -> EnrichmentResult:
    """
    Fetch page head and extract published_at and/or authors.

    Parse order: JSON-LD → Open Graph → meta tags → semantic HTML → trafilatura.
    Stops as soon as both requested fields are satisfied.
    BeautifulSoup is instantiated exactly once per call.
    """
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

        # Parse once — O4 fix: soup passed to all strategy functions below
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_head, "lxml")

        def _satisfied() -> bool:
            """True when every requested field has been filled."""
            return (not need_date or bool(result.published_at)) and \
                   (not need_authors or bool(result.authors))

        # Strategy 1: JSON-LD (most structured, highest fidelity)
        _try_json_ld(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        # Strategy 2: Open Graph meta tags
        _try_opengraph(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        # Strategy 3: Standard / proprietary meta tags
        _try_meta_tags(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        # Strategy 4: Semantic HTML (<time> elements, rel=author)
        _try_semantic_html(soup, result, need_date=need_date, need_authors=need_authors)
        if _satisfied():
            result.timing_ms = t.elapsed_ms
            return result

        # Strategy 5: trafilatura.metadata — operates on raw HTML string, not soup
        _try_trafilatura(html_head, url, result, need_date=need_date, need_authors=need_authors)

        result.timing_ms = t.elapsed_ms
    return result


def _fetch_head(url: str, timeout: int) -> str:
    """
    Fetch first 16KB of an HTML page with minimal bandwidth.

    Steps:
    1. HEAD request — check Content-Type (skip non-HTML) and Accept-Ranges header.
    2. If Accept-Ranges: bytes → Range GET (transfers only first 16KB over the wire).
    3. Otherwise → streaming GET truncated at _HEAD_BYTES (stops reading, closes connection).

    Fixes O1 (Range header unreliable) and O2 (non-HTML waste).
    """
    with create_httpx_client(timeout=timeout) as client:
        # Step 1: HEAD probe
        try:
            head_resp = client.head(url)
            content_type = head_resp.headers.get("content-type", "").lower()
            if "html" not in content_type:
                log.debug("Skipping non-HTML URL %s (content-type: %s)", url, content_type)
                return ""
            accepts_range = head_resp.headers.get("accept-ranges", "").lower() == "bytes"
        except Exception:
            # HEAD failed (some servers reject it) — proceed with streaming GET
            accepts_range = False

        # Step 2: Range GET if server supports it — minimal wire transfer
        if accepts_range:
            try:
                resp = client.get(url, headers={"Range": f"bytes=0-{_HEAD_BYTES - 1}"})
                if resp.status_code in (200, 206):
                    return resp.text[:_HEAD_BYTES]
            except Exception:
                pass  # Fall through to streaming

        # Step 3: Streaming GET — read until _HEAD_BYTES then close
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes(chunk_size=4096):
                chunks.append(chunk)
                total += len(chunk)
                if total >= _HEAD_BYTES:
                    break  # Connection closed here — no further data transferred
            return b"".join(chunks)[:_HEAD_BYTES].decode("utf-8", errors="replace")


# --- JSON-LD extraction ---
# Accepts soup (BeautifulSoup) — O4 fix: no re-parse

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
            # Handle @graph array
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

                # O5 fix: early exit once both satisfied
                if (not need_date or result.published_at) and (not need_authors or result.authors):
                    return

    except Exception as exc:
        log.debug("JSON-LD extraction failed: %s", exc)


# --- Open Graph extraction ---
# Accepts soup — O4 fix

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
                if not content.startswith("http"):   # skip URL-valued author fields
                    result.authors = [content]
                    result.enriched_fields.append("authors")
                    result.source = result.source or "opengraph"

            # O5 fix: early exit
            if (not need_date or result.published_at) and (not need_authors or result.authors):
                return

    except Exception as exc:
        log.debug("OpenGraph extraction failed: %s", exc)


# --- Standard + proprietary meta tags ---
# Accepts soup — O4 fix

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
    "byl",  # NYT / legacy news
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
            # name or itemprop, lowercased for case-insensitive match
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

            # O5 fix: early exit
            if (not need_date or result.published_at) and (not need_authors or result.authors):
                return

    except Exception as exc:
        log.debug("Meta tag extraction failed: %s", exc)


# --- Semantic HTML elements ---
# Accepts soup — O4 fix

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
                        break  # O5: stop scanning <time> tags once found

        if need_authors and not result.authors:
            for a_el in soup.find_all("a", rel=True):
                if "author" in (a_el.get("rel") or []):
                    name = a_el.get_text(strip=True)
                    if name:
                        result.authors = [name]
                        result.enriched_fields.append("authors")
                        result.source = result.source or "semantic-html"
                        break  # O5: stop scanning <a rel=author> once found

    except Exception as exc:
        log.debug("Semantic HTML extraction failed: %s", exc)


# --- trafilatura fallback ---
# Operates on raw HTML string (trafilatura doesn't accept soup)

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


# --- Batch enrichment (ThreadPoolExecutor — O3 fix) ---

def enrich_search_results(
    results: list[dict],
    *,
    concurrency: int = 5,
    timeout: int = 8,
) -> list[dict]:
    """
    Enrich a list of search result dicts in-place.

    Only fetches pages where published_at or authors is missing.
    Uses ThreadPoolExecutor (not asyncio.run) — safe to call from any context,
    including inside an existing event loop. Consistent with _fetch_parallel().

    Returns the same list (modified in-place) for convenience.
    """
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
        list(pool.map(_do_one, to_enrich))  # list() forces all futures to complete

    return results
```

---

## 5. CLI Integration — Revised Flag Model

### Flag inversion from previous plan

| Previous (opt-in) | Now (default-on, opt-out) |
|---|---|
| `--enrich-meta` enables enrichment | `--no-enrich` disables enrichment |
| `--cite` enables citations array | `--no-cite` disables citations array |
| Default: no enrichment, no citations | Default: enrichment + citations always |

### 5.1 Revised `search` flags

```python
# web.py — replace previous --enrich-meta / --cite with their inverses
p_search.add_argument(
    "--no-enrich",
    dest="no_enrich",
    action="store_true",
    default=False,
    help="Skip head-fetching for missing published_at / authors. "
         "Faster but sourcing may be incomplete. "
         "Default: enrichment is ON.",
)
p_search.add_argument(
    "--no-cite",
    dest="no_cite",
    action="store_true",
    default=False,
    help="Omit citations[] array and citation_index from output. "
         "Default: citations are always emitted.",
)
p_search.add_argument(
    "--enrich-concurrency",
    dest="enrich_concurrency",
    type=int,
    default=5,
    help="Max concurrent head-fetch requests for metadata enrichment (default: 5).",
)
p_search.add_argument(
    "--enrich-timeout",
    dest="enrich_timeout",
    type=int,
    default=8,
    help="Per-request timeout in seconds for enrichment head-fetches (default: 8).",
)
```

### 5.2 Revised `cmd_search` pipeline

The full default pipeline, in order:

```python
def cmd_search(args: argparse.Namespace) -> None:
    from _searxng import search

    # 1. Search (with fallback chain — unchanged)
    result = search(...)
    if result.status == "failed" and not getattr(args, "no_fallback", False):
        ...  # Brave → ddgs fallback (unchanged)

    # 2. --fetch-top: fetch full content for top N results (unchanged)
    #    Also backfills published_at / authors from fetched content for free
    fetch_top = getattr(args, "fetch_top", 0)
    if fetch_top > 0 and result.status != "failed" and result.results:
        top_urls = [r["url"] for r in result.results[:fetch_top] if r.get("url")]
        fetched = _fetch_parallel(top_urls, concurrency=args.fetch_concurrency, timeout=args.fetch_timeout)
        for r, content in zip(result.results[:fetch_top], fetched):
            r["content"] = content
            # Free backfill — no extra round-trip
            if not r.get("published_at") and content.get("published_at"):
                r["published_at"] = content["published_at"]
                r.setdefault("meta_enriched", []).append("published_at")
                r["meta_source"] = "fetch"
            if not r.get("authors") and content.get("authors"):
                r["authors"] = content["authors"]
                r.setdefault("meta_enriched", []).append("authors")
                r.setdefault("meta_source", "fetch")

    # 3. Enrichment (DEFAULT ON — head-fetch remaining gaps)
    if not getattr(args, "no_enrich", False) and result.status != "failed" and result.results:
        from _meta_enrichment import enrich_search_results
        enrich_search_results(
            result.results,
            concurrency=getattr(args, "enrich_concurrency", 5),
            timeout=getattr(args, "enrich_timeout", 8),
        )

    # 4. Citations (DEFAULT ON — always emit citations[] + citation_index)
    result_dict = result.to_dict()
    if not getattr(args, "no_cite", False) and result.results:
        citations = []
        for i, r in enumerate(result.results, start=1):
            r["citation_index"] = i
            domain = r.get("domain", "")
            date = r.get("published_at", "")
            authors = r.get("authors", [])
            title = r.get("title", r.get("url", ""))
            url = r.get("url", "")
            parts = [f"[{i}]", title]
            if authors:
                parts.append(f"by {', '.join(authors)}")
            if domain:
                parts.append(f"— {domain}")
            if date:
                parts.append(f"({date})")
            else:
                parts.append("(date unknown)")
            parts.append(url)
            citations.append(" ".join(p for p in parts if p))
        result_dict["citations"] = citations

    emit(result_dict, pretty=args.pretty)
```

Note: `(date unknown)` is emitted explicitly when no date was found even after enrichment. This is intentional — it signals to the agent that the source exists but the date could not be determined, rather than silently omitting date context.

### 5.3 `fetch` command — citations always included when metadata is present

`fetch` already extracts `published_at` and `authors` via trafilatura. The change: always include a `citation` object in output when at least `url` and `title` are present (which is always). No flag needed — it is always present and can be ignored.

```python
# At end of cmd_fetch, before emit():
result.citation = _build_citation(result)   # always — never conditional
_append_citation_to_markdown(result)         # always appends source block to markdown
```

The `_build_citation()` and `_append_citation_to_markdown()` helpers handle missing fields gracefully — partial citations with `"date unknown"` / empty authors are still valid sources.

### 5.4 `fetch-batch` — citation per NDJSON line

Each result in `fetch-batch` NDJSON output gains a `citation` object using the same `_build_citation()` helper. No flag needed.

---

## 6. Changes to `_normalize.py` (SearchResult dataclass)

Add optional `citations` field:

```python
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
    citations: list[str] = field(default_factory=list)   # NEW

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("error"):
            d.pop("error", None)
        if not d.get("citations"):           # omit if empty (consistent with other fields)
            d.pop("citations", None)
        return d
```

Add `citation` field to `WebResult`:

```python
@dataclass
class WebResult:
    # ... existing fields ...
    citation: Optional[dict] = None          # NEW — populated by --cite flag
```

---

## 7. `_deps.py` changes

Add `_meta_enrichment` to the command deps map. It uses only `httpx` + `bs4` which are already in `CORE_DEPS` — no new pip packages needed.

```python
_COMMAND_DEPS: dict[str, list[str]] = {
    "search": CORE_DEPS + ["ddgs"],
    "fetch": CORE_DEPS,
    "crawl": CORE_DEPS + CRAWL_DEPS,
    "scrape": CORE_DEPS,
    "scrape-crawl4ai": CORE_DEPS + CRAWL_DEPS,
    "extract": ["trafilatura"],
    "discover": ["trafilatura"],
    # meta enrichment shares CORE_DEPS — no separate entry needed
}
```

No entry needed — `_meta_enrichment.py` uses only `httpx`, `bs4`, and `trafilatura` which are all in `CORE_DEPS`.

---

## 8. Expected Output After Enhancement

### Default `search "query"` (no flags — fully sourced by default)

```json
{
  "status": "ok",
  "command": "search",
  "query": "neural scaling laws",
  "results": [
    {
      "citation_index": 1,
      "url": "https://arxiv.org/abs/2001.08361",
      "title": "Scaling Laws for Neural Language Models",
      "snippet": "We study empirical scaling laws for language model performance...",
      "engine": "google",
      "engines": ["google", "bing"],
      "score": 2.1,
      "domain": "arxiv.org",
      "published_at": "2020-01-23",
      "authors": ["Jared Kaplan", "Sam McCandlish"],
      "quality_score": 0.87,
      "meta_enriched": ["published_at", "authors"],
      "meta_source": "json-ld"
    },
    {
      "citation_index": 2,
      "url": "https://blog.example.com/scaling",
      "title": "Understanding Scaling Laws",
      "snippet": "...",
      "engine": "google",
      "domain": "blog.example.com",
      "published_at": "",
      "authors": [],
      "quality_score": 0.61,
      "meta_enriched": [],
      "meta_source": ""
    }
  ],
  "total_results": 10,
  "timing_ms": 1420,
  "citations": [
    "[1] Scaling Laws for Neural Language Models by Jared Kaplan, Sam McCandlish — arxiv.org (2020-01-23) https://arxiv.org/abs/2001.08361",
    "[2] Understanding Scaling Laws — blog.example.com (date unknown) https://blog.example.com/scaling"
  ]
}
```

Note: result [2] still gets a citation entry even though enrichment found nothing. `(date unknown)` is explicit — agents can see the gap and decide whether to follow up with `fetch` to get more metadata.

### `search "query" --no-enrich --no-cite` (speed mode)

```json
{
  "status": "ok",
  "command": "search",
  "query": "neural scaling laws",
  "results": [
    {
      "url": "https://arxiv.org/abs/2001.08361",
      "title": "Scaling Laws for Neural Language Models",
      "snippet": "...",
      "domain": "arxiv.org",
      "published_at": "2020-01-23",
      "quality_score": 0.87
    }
  ],
  "total_results": 10,
  "timing_ms": 340
}
```

### Default `fetch "url"` (citation always present)

```json
{
  "status": "ok",
  "command": "fetch",
  "url": "https://example.com/article",
  "title": "Article Title",
  "published_at": "2025-03-12",
  "authors": ["Jane Smith"],
  "markdown": "# Article Title\n\nContent...\n\n---\n**Source:** [Article Title](https://example.com/article) · example.com · Published 2025-03-12 · By Jane Smith",
  "citation": {
    "url": "https://example.com/article",
    "title": "Article Title",
    "site_name": "example.com",
    "published_at": "2025-03-12",
    "authors": ["Jane Smith"],
    "citation_text": "Jane Smith. \"Article Title\". example.com. 2025-03-12. https://example.com/article"
  },
  "confidence": 0.92,
  "timing_ms": 412
}
```

---

## 9. Documentation Updates

### `SKILL.md` — search section (line 98, replace existing flag list)

Replace:
```
bin/web-intel search "query" [--engines google,brave] [--categories general] [--language en] [--time-range week] [--max-results 10] [--no-rerank] [--no-fallback] [--fetch-top N] [--fetch-concurrency 3] [--fetch-timeout 20]
```

With:
```
bin/web-intel search "query" [--engines google,brave] [--categories general] [--language en]
  [--time-range week] [--max-results 10] [--no-rerank] [--no-fallback]
  [--fetch-top N] [--fetch-concurrency 3] [--fetch-timeout 20]
  [--no-enrich] [--enrich-concurrency 5] [--enrich-timeout 8]
  [--no-cite]
```

Update result fields line:
```
Result fields: `url`, `title`, `snippet`, `engine`, `engines[]`, `score`, `domain`, `published_at`,
`authors`, `quality_score`, `category`, `citation_index`, `meta_enriched[]`, `meta_source`.
Top-level: `citations[]` — always present, one entry per result, format:
  "[N] Title by Author — domain (YYYY-MM-DD) url"  or "(date unknown)" when unavailable.

Opt-out flags:
- `--no-enrich`: Skip head-fetch enrichment for missing published_at / authors. Faster; sourcing may be incomplete.
- `--no-cite`: Omit citations[] array and citation_index from output.
- `--enrich-concurrency N`: Max concurrent enrichment fetches (default: 5).
- `--enrich-timeout N`: Per-request enrichment timeout in seconds (default: 8).
```

### `SKILL.md` — fetch section

Add after existing flags:
```
fetch always returns a citation object and appends a source attribution block to markdown:
- citation.url, citation.title, citation.site_name, citation.published_at, citation.authors, citation.citation_text
- markdown ends with: --- **Source:** [Title](url) · site · Published date · By author
  (fields omitted if not found; published_at shows "date unknown" if absent)
```

### `references/output-schema.md`

1. Update search result item schema to include all new fields with descriptions:
   - `published_at`: ISO `YYYY-MM-DD` or `""`. Always attempted. Empty means not found even after enrichment.
   - `authors`: `[]` or list of strings. Always attempted.
   - `domain`: Always populated from URL for all backends.
   - `citation_index`: 1-based integer. Present unless `--no-cite`.
   - `meta_enriched`: `["published_at", "authors"]` — which fields were found via head-fetch.
   - `meta_source`: `"json-ld" | "opengraph" | "meta" | "semantic-html" | "trafilatura" | ""` — signal that found the metadata.
2. Add `citations[]` to top-level search envelope with format spec and `(date unknown)` note.
3. Add `citation` object to WebResult schema (always present in `fetch`/`crawl`/`extract`).
4. Add latency note: enrichment adds ~0–500ms total (concurrent, skips results that already have data).

### `references/advanced-patterns.md`

Replace old `--enrich-meta --cite` examples with plain invocations (no flags needed):

```bash
# Default search — fully sourced, citations always included
bin/web-intel search "neural scaling laws" --pretty

# Full content + citations (fetch-top backfills metadata for free)
bin/web-intel search "query" --fetch-top 3 --pretty

# Speed mode — skip enrichment and citations (for high-volume pipelines)
bin/web-intel search "query" --no-enrich --no-cite --pretty

# Compose a cited research answer
bin/web-intel search "transformer attention mechanisms" \
  | jq -r '
    "## Research Summary\n",
    (.results[] | "### [\(.citation_index)] \(.title) (\(.published_at // "date unknown"))\n\(.snippet)\n"),
    "\n## References",
    (.citations[])
  '

# Use citations[] as a ready-made reference list for follow-up fetches
bin/web-intel search "RLHF alignment" \
  | jq -r '.results[] | select(.published_at != "") | .url' \
  | bin/web-intel fetch-batch --concurrency 3 --max-tokens 2000
```

---

## 10. Implementation Order

| Step | File(s) | Effort | Depends on |
|---|---|---|---|
| **1** | `_normalize.py`: add `normalize_date()`, `extract_domain()` | XS | — |
| **2** | `_searxng.py`: wire `normalize_date()` to `published_at` | XS | Step 1 |
| **3** | `_search_fallback.py`: wire `normalize_date()` + `extract_domain()` for both backends | XS | Step 1 |
| **4** | `_trafilatura_extract.py`: wire `normalize_date()` to `meta.date` | XS | Step 1 |
| **5** | `_normalize.py`: add `citation` field to `WebResult`, `citations` to `SearchResult` | XS | — |
| **6** | `scripts/_meta_enrichment.py`: create new file with full implementation above | M | Step 1 |
| **7** | `web.py`: **remove** `--enrich-meta` / `--cite`, **add** `--no-enrich` / `--no-cite` / `--enrich-concurrency` / `--enrich-timeout` to `search` parser | S | — |
| **8** | `web.py`: restructure `cmd_search` to run enrichment + citations by default (see §5.2) | S | Steps 6, 7 |
| **9** | `web.py`: add `_build_citation()` + `_append_citation_to_markdown()` helpers; call unconditionally in `cmd_fetch` and `cmd_fetch_batch` | S | Step 5 |
| **10** | `web.py`: backfill `authors`/`published_at` from fetch-top content into result items | XS | Step 8 |
| **11** | `SKILL.md`, `references/output-schema.md`, `references/advanced-patterns.md`: docs update | S | Steps 1–10 |

**Estimated total:** ~3–4 hours.  
**Zero new pip dependencies.**

---

## 11. Latency Impact

| Scenario | Added latency | Notes |
|---|---|---|
| All results already have `published_at` + `authors` | ~0ms | Enrichment skipped entirely per result |
| SearXNG results with partial dates | ~0ms | Normalization only, no fetch |
| ddgs / Brave results (dates absent) | ~100–500ms total | Concurrent head-fetches, capped at `--enrich-concurrency` |
| With `--fetch-top N` | ~0ms extra for those N | Full content already fetched; backfill is free |
| `--no-enrich` | ~0ms | Full skip |

Worst case: 10 results with no dates, no `--fetch-top`, concurrency=5 → two batches of 5 concurrent head-fetches → ~300–600ms total added to the search call.

---

## 12. Testing Notes

The existing test suite in `tests/` uses no network. New tests for `_meta_enrichment.py` should:

1. Test `normalize_date()` with all input formats (ISO, RFC 2822, slash format, month names, relative strings → `""`)
2. Test `_try_json_ld()` with Article/NewsArticle/BlogPosting fixtures
3. Test `_try_opengraph()` with `article:published_time` and `article:author` fixtures
4. Test `_try_meta_tags()` with `name="date"`, `name="DC.date"`, `name="author"` fixtures
5. Test `enrich_search_results()` with a list where some items have dates and some don't — verify only missing ones trigger a fetch
6. Test `_build_citation()` with partial WebResult (missing authors, missing date) — verify `"date unknown"` placeholder in `citation_text`
7. Test `cmd_search` with `--no-enrich --no-cite` — verify enrichment and `citations[]` are both absent
8. Test default `cmd_search` output — verify `citations[]` is always present and every result has `citation_index`

All testable without network using HTML string fixtures and mocked HTTP.
