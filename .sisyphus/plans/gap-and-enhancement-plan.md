# web-intel: Gap & Enhancement Implementation Plan

> Generated: 2026-04-26  
> Scope: All gaps and enhancement opportunities identified in the architectural review.  
> Each item has a priority, effort estimate, affected files, and precise implementation spec.

---

## Priority Legend

| Symbol | Meaning |
|--------|---------|
| 🔥 | Critical — fixes a real bug or blocks an 80% use case |
| ⭐ | High — significant usability win, no existing workaround |
| 🔵 | Medium — quality of life, completeness |
| ⚪ | Low — polish, nice-to-have |

---

## Gap Coverage Matrix

Each plan item is mapped to its source gap. Items without a gap source are enhancements, not gap fixes.

| Gap | Description | Covered by | Coverage |
|-----|-------------|------------|----------|
| Gap 1 | `search` has no Docker-free fallback | Item 4 + Item 4a (doctor integration) — uses `ddgs` | ✅ Complete |
| Gap 2 | Search results too shallow (no date/domain/score) | Item 7 + Item 7a (relevance ranking) | ✅ Complete |
| Gap 3 | `scrape` only one selector per call | Item 8 | ✅ Complete |
| Gap 4 | `discover` has no URL metadata or depth | Item 9 + Item 9a (depth tracking) | ✅ Complete |
| Gap 5 | No token-budget / chunking awareness | Items 5, 6, 5a (chunked access) | ✅ Complete |
| Gap 6 | Triple Trafilatura extraction pass | Item 2 | ✅ Complete |
| Gap 7 | `get_raw_html` returns markdown not HTML | Item 1 | ✅ Complete |
| Gap 8 | No rate-limiting enforcement | Item 10 + Item 8a (enforcement note) | ✅ Complete |
| Gap 9 | No unit tests | Item 13 | ✅ Complete |

Items **3, 11, 12, 14** are enhancements (not gap fixes) — included because they are high-value and low-effort.

---

## Summary Table

| # | Item | Priority | Effort | Gap | Category |
|---|------|----------|--------|-----|----------|
| 1 | Fix `get_raw_html` returning markdown instead of HTML | 🔥 | S | Gap 7 | Bug fix |
| 2 | Eliminate triple Trafilatura extraction pass | 🔥 | S | Gap 6 | Performance |
| 3 | `search --fetch-top N` one-shot pipeline | 🔥 | M | Enhancement | New command flag |
| 4 | Search fallback chain (SearXNG → Brave → ddgs multi-engine) | 🔥 | S | Gap 1 | Reliability |
| 4a | `doctor` reports search fallback readiness | 🔥 | XS | Gap 1 | Reliability |
| 5 | `--max-tokens N` / `--truncate N` on fetch/crawl/extract | ⭐ | S | Gap 5 | Agent ergonomics |
| 5a | `fetch --chunk-index I --chunk-count N` paginated access | ⭐ | S | Gap 5 | Agent ergonomics |
| 6 | `fetch --relevant-to "query"` semantic section filter | ⭐ | M | Gap 5 | Agent ergonomics |
| 7 | Enrich search results (date, domain, multi-engine dedup) | ⭐ | S | Gap 2 | Data quality |
| 7a | Search result relevance/quality ranking signal | ⭐ | S | Gap 2 | Data quality |
| 8 | `scrape --schema JSON` multi-field structured extraction | ⭐ | M | Gap 3 | New capability |
| 8a | Document `fetch-batch` as the only safe parallel path | 🔵 | XS | Gap 8 | Reliability |
| 9 | Enrich `discover` results (title, last-modified, priority) | ⭐ | S | Gap 4 | Data quality |
| 9a | `discover --mode crawl` BFS depth tracking | 🔵 | S | Gap 4 | Data quality |
| 10 | `fetch-batch` command (parallel URL list, semaphore-guarded) | ⭐ | M | Gap 8 | Performance |
| 11 | Computed confidence score (content density ratio) | 🔵 | S | Enhancement | Quality signal |
| 12 | `fetch --diff` change detection | 🔵 | M | Enhancement | Monitoring |
| 13 | Unit test suite for pure-python modules | 🔵 | M | Gap 9 | Correctness |
| 14 | `--wait-for-text` retry on static fetch | 🔵 | S | Enhancement | Reliability |
| 15 | `char_count` + `truncated` fields in envelope | ⚪ | XS | Gap 5 | Introspection |

---

## Item 1 — Fix `get_raw_html` returning markdown instead of HTML

**Priority:** 🔥 Bug  
**Effort:** S (~30 min)  
**Root cause:** `_crawl4ai_crawl.py:get_raw_html()` returns `result.text or result.markdown`. But `WebResult.text` is populated from `result.extracted_content` — Crawl4AI's extracted text, not raw HTML. Feeding this into BS4's table parser silently produces no tables because BS4 receives markdown-flavored text, not `<table>` elements.

**Affected files:**
- `scripts/_crawl4ai_crawl.py`
- `scripts/_normalize.py` (add `html` field to `WebResult`)

**Implementation:**

1. Add `html: str = ""` field to `WebResult` in `_normalize.py`.

2. In `_crawl_local()`, populate `html` from the raw HTML that Crawl4AI exposes:
   ```python
   # Crawl4AI CrawlResult has a .html attribute (raw HTML before extraction)
   html=getattr(result, "html", "") or "",
   ```

3. In `_crawl_docker()`, populate `html` from `result_data.get("html", "")`.

4. In `get_raw_html()`, return `result.html` as the primary source, with `result.text` only as a last resort:
   ```python
   def get_raw_html(...) -> str:
       result = crawl(...)
       # html = raw HTML from browser; text = extracted content; markdown = processed markdown
       return result.html or result.text or ""
   ```

5. Always suppress `html` from `to_dict()` output — it is large and only consumed internally by `scrape`. No flag needed:
   ```python
   # In WebResult.to_dict(), always exclude 'html' — internal use only
   d.pop("html", None)
   ```
   > **Note:** The `html` field exists solely as an in-process carrier between `_crawl4ai_crawl.py` and `_bs4_scrape.py`. It is never serialized to the agent-facing JSON envelope.

**Tests:** Add a unit test asserting `get_raw_html` returns a string containing `<` characters (i.e., is actually HTML, not markdown).

---

## Item 2 — Eliminate triple Trafilatura extraction pass

**Priority:** 🔥 Performance  
**Effort:** S (~45 min)  
**Root cause:** `_trafilatura_extract.py:extract_from_html()` calls `trafilatura.extract()` three times:
1. `output_format="txt"` → for `text` field
2. `output_format="markdown"` → for `markdown` field  
3. `output_format="xmltei"` with `with_metadata=True` → for metadata (then ignored, `_parse_metadata` uses a 4th call via `extract_metadata`)

This is ~3–4x the extraction cost. The `xmltei` result is never used (variable `metadata` is assigned but never read).

**Affected files:**
- `scripts/_trafilatura_extract.py`

**Implementation:**

1. Extract once to markdown (primary output format). Derive plain text by stripping markdown syntax:
   ```python
   import re

   def _markdown_to_text(md: str) -> str:
       """Strip markdown formatting to produce plain text."""
       text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', md)  # links
       text = re.sub(r'[#*_`~>|]', '', text)                 # formatting chars
       text = re.sub(r'\n{3,}', '\n\n', text)                # excess newlines
       return text.strip()
   ```

2. Remove the unused `metadata = trafilatura.extract(... output_format="xmltei" ...)` call entirely.

3. The `extract_from_html` function becomes a single `trafilatura.extract()` call (markdown format), then `_parse_metadata()` separately.

4. Before changing, add a regression test comparing the old and new outputs on a known HTML fixture — they should be functionally equivalent.

**Expected speedup:** ~60% reduction in extraction latency for `fetch` and `extract` commands.

---

## Item 3 — `search --fetch-top N` one-shot pipeline

**Priority:** 🔥 New capability  
**Effort:** M (~3 hours)  
**Rationale:** This is the most common agent research task — search for a topic, then read the top results. Currently it requires shell scripting with `jq` and loops. Collapsing it into one command is the single highest-leverage improvement.

**Affected files:**
- `scripts/web.py` (new flag on `search` subcommand + `cmd_search` handler)
- `scripts/_searxng.py` (no change needed)
- `scripts/_trafilatura_extract.py` (reuse `fetch_and_extract`)

**New CLI signature:**
```bash
web-intel search "query" --fetch-top 3 [--fetch-concurrency 3] [--fetch-timeout 20]
```

**Output envelope change:**
Each result in `results[]` gains an optional `content` object when `--fetch-top` is used:
```json
{
  "url": "https://...",
  "title": "...",
  "snippet": "...",
  "engine": "google",
  "score": 1.5,
  "content": {
    "status": "ok",
    "markdown": "# Full article content...",
    "confidence": 0.85,
    "timing_ms": 450,
    "fetch_mode": "httpx"
  }
}
```
Results beyond `--fetch-top N` do not have a `content` key.

**Implementation:**

1. Add args to `p_search` in `build_parser()`:
   ```python
   p_search.add_argument("--fetch-top", dest="fetch_top", type=int, default=0)
   p_search.add_argument("--fetch-concurrency", dest="fetch_concurrency", type=int, default=3)
   p_search.add_argument("--fetch-timeout", dest="fetch_timeout", type=int, default=20)
   ```

2. In `cmd_search()`, after getting search results, if `args.fetch_top > 0`:
   ```python
   if args.fetch_top > 0 and result.status == "ok":
       top_urls = [r["url"] for r in result.results[:args.fetch_top]]
       fetched = _fetch_parallel(top_urls, concurrency=args.fetch_concurrency, timeout=args.fetch_timeout)
       for r, content in zip(result.results[:args.fetch_top], fetched):
           r["content"] = content
   ```

3. Implement `_fetch_parallel()` in `web.py` using `asyncio` + `asyncio.gather`:
   ```python
   import asyncio

   def _fetch_parallel(urls: list[str], *, concurrency: int, timeout: int) -> list[dict]:
       """Fetch multiple URLs concurrently. Returns list of content dicts."""
       sem = asyncio.Semaphore(concurrency)

       async def _fetch_one(url: str) -> dict:
           async with sem:
               loop = asyncio.get_event_loop()
               try:
                   result = await loop.run_in_executor(
                       None, lambda: fetch_and_extract(url, timeout=timeout)
                   )
                   return {
                       "status": result.status,
                       "markdown": result.markdown,
                       "confidence": result.confidence,
                       "timing_ms": result.timing_ms,
                       "fetch_mode": result.fetch_mode,
                       "error": result.error,
                   }
               except Exception as exc:
                   return {"status": "failed", "error": str(exc)}

       async def _run_all() -> list[dict]:
           return await asyncio.gather(*[_fetch_one(u) for u in urls])

       return asyncio.run(_run_all())
   ```

4. Update `_COMMAND_DEPS` to include fetch deps when `--fetch-top` is used:
   In `main()`, when `args.command == "search"` and `args.fetch_top > 0`, call `ensure_deps("fetch")`.

5. Update `references/routing-guide.md` with the new pattern.

**Tests:** Add e2e test asserting `search --fetch-top 1` returns `results[0].content.markdown` non-empty.

---

## Item 4 — Search fallback chain (no Docker required)

**Priority:** 🔥 Reliability  
**Effort:** S (~2 hours, reduced from M by using `ddgs` instead of custom scrapers)  
**Rationale:** `search` returns `failed` if SearXNG isn't running. For agents in CI, sandboxed environments, or any machine without Docker, search is dead. The [`ddgs`](https://github.com/deedy5/ddgs) library provides a zero-config fallback across multiple engines (DuckDuckGo, Bing, Brave, Mojeek, Yandex, Yahoo) with TLS fingerprint impersonation via `primp` — replacing ~200 lines of custom DDG+StartPage HTML scraping with ~15 lines.

**Decision rationale (DDG+StartPage → `ddgs`):**  
The original plan specified a custom DuckDuckGo Lite HTML scraper + StartPage React-JSON scraper merged in parallel. `ddgs` v9+ makes this unnecessary:
- Eliminates sc-code session management (StartPage bot-detection token)
- Eliminates React-serialized JSON parsing for StartPage results  
- Eliminates DDG lite URL redirect decoding and selector maintenance
- Provides broader engine coverage (6+ backends vs. 2)
- Maintainer actively fixes broken backends (Google disabled same-day when it broke)

**Trade-off accepted:** `published_at` is always `""` for `ddgs` text results (`TextResult` has no date field). This is acceptable — the fallback is a degraded mode, and Item 7's date enrichment operates on SearXNG results only.

**Affected files:**
- `scripts/_search_fallback.py` (new file — much simpler than original spec)
- `scripts/web.py` (`cmd_search` handler)
- `scripts/_deps.py` — add `"ddgs"` to `_COMMAND_DEPS["search"]` (replaces `bs4` from original spec)
- `SKILL.md` (document the fallback behavior)

**Fallback chain:**
```
SearXNG (Docker) → ddgs(backend="auto") → error
```

If `BRAVE_API_KEY` is set in `.env`, insert the keyed Brave API tier before `ddgs`:
```
SearXNG → Brave Search API (keyed) → ddgs(backend="auto") → error
```

> **Note:** `ddgs` with `backend="auto"` already fans out to Brave (no key), Bing, Mojeek, Yandex, Yahoo, and DuckDuckGo in parallel — so the `ddgs` tier provides strong multi-engine coverage on its own.

**New file `scripts/_search_fallback.py`:**

```python
"""Fallback search implementations when SearXNG is unavailable."""
from __future__ import annotations
from _config import create_httpx_client, get_logger
from _normalize import SearchResult, Timer

log = get_logger("search_fallback")


# ---------------------------------------------------------------------------
# ddgs — multi-engine metasearch (DuckDuckGo, Bing, Brave, Mojeek, Yandex, Yahoo)
# ---------------------------------------------------------------------------

def search_ddgs(
    query: str,
    *,
    max_results: int = 10,
    timeout: int = 15,
) -> SearchResult:
    """Search via ddgs (https://github.com/deedy5/ddgs).

    Uses backend="auto" which fans out to all enabled engines in parallel
    (DuckDuckGo, Bing, Brave, Mojeek, Yandex, Yahoo) and deduplicates by URL.
    TLS fingerprint impersonation via primp mitigates bot detection.

    Note: TextResult has no date field — published_at is always "".
    Wrap calls with RatelimitException handling; ddgs does not retry internally.
    Pin to a specific minor version in requirements: ddgs>=9.14,<10
    """
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException

    with Timer() as t:
        try:
            raw = DDGS(timeout=timeout).text(query, max_results=max_results, backend="auto")
        except RatelimitException as exc:
            return SearchResult(
                query=query, status="failed",
                error=f"ddgs rate limited: {exc}", timing_ms=t.elapsed_ms,
            )
        except Exception as exc:
            return SearchResult(
                query=query, status="failed",
                error=f"ddgs fallback failed: {exc}", timing_ms=t.elapsed_ms,
            )

    if not raw:
        return SearchResult(
            query=query, status="partial",
            error="ddgs returned no results", timing_ms=t.elapsed_ms,
        )

    results = [
        {
            "url": r.get("href", ""),
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "engine": "ddgs",
            "score": 0,
            "published_at": "",  # TextResult has no date field
        }
        for r in raw
        if r.get("href")
    ]
    return SearchResult(
        query=query, results=results,
        total_results=len(results), timing_ms=t.elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Brave Search API (keyed — optional, higher quality than ddgs Brave scrape)
# ---------------------------------------------------------------------------

def search_brave(
    query: str,
    *,
    api_key: str,
    max_results: int = 10,
    timeout: int = 10,
) -> SearchResult:
    """Search via Brave Search API. Requires BRAVE_API_KEY."""
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
                                error=f"Brave Search API failed: {exc}", timing_ms=t.elapsed_ms)

    web_results = data.get("web", {}).get("results", [])[:max_results]
    results = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("description", ""),
            "engine": "brave",
            "score": r.get("relevance_score", 0),
            "published_at": r.get("page_age", ""),
        }
        for r in web_results
    ]
    return SearchResult(query=query, results=results, total_results=len(results), timing_ms=t.elapsed_ms)
```

**Changes to `cmd_search()` in `web.py`:**
```python
def cmd_search(args: argparse.Namespace) -> None:
    # Try SearXNG first
    from _searxng import search
    result = search(args.query, ...)

    # Fallback if SearXNG failed and fallbacks not disabled
    if result.status == "failed" and not getattr(args, "no_fallback", False):
        import os
        from _search_fallback import search_brave, search_ddgs

        brave_key = os.environ.get("BRAVE_API_KEY")
        if brave_key:
            log.info("SearXNG unavailable, trying Brave Search API fallback")
            result = search_brave(args.query, api_key=brave_key, max_results=args.max_results)

        if result.status == "failed":
            log.info("SearXNG unavailable, trying ddgs multi-engine fallback")
            result = search_ddgs(args.query, max_results=args.max_results)

        if result.status != "failed":
            result.error = (result.error or "") + " [SearXNG unavailable, used fallback]"

    emit(result.to_dict(), pretty=args.pretty)
```

Add `--no-fallback` flag to `p_search` for agents that want to fail fast.

**`_deps.py` change:**
```python
# In _COMMAND_DEPS, update the "search" entry:
"search": ["httpx", "httpx-retries", "trafilatura", "beautifulsoup4", "lxml", "ddgs"],
# Note: bs4/lxml remain because they're still used by other search-related paths (scrape).
# ddgs itself pulls in primp (Rust TLS client) as a transitive dep — no extra action needed.
```

**Config addition to `.env.example`:**
```
# Optional: Brave Search API key for a higher-quality keyed fallback before ddgs
# BRAVE_API_KEY=
```

**`doctor` update — complete spec (Item 4a):**

This is a required part of Item 4, not optional. Agents run `doctor` to know what's available before issuing commands. Without a `doctor` update, agents will still see `search` as `not_ready` even though the fallback works.

Add two new checks to `cmd_doctor()` in `web.py`:

```python
# Check: Brave API key configured (optional keyed fallback)
brave_key = os.environ.get("BRAVE_API_KEY")
checks.append({
    "check": "search_fallback_brave",
    "status": "ok" if brave_key else "optional",
    "hint": "" if brave_key else "Set BRAVE_API_KEY in .env for a higher-quality keyed search fallback",
})

# Check: ddgs importable (zero-config fallback)
ddgs_ok = False
try:
    import importlib
    importlib.import_module("ddgs")
    ddgs_ok = True
except ImportError:
    pass
checks.append({
    "check": "search_fallback_ddgs",
    "status": "ok" if ddgs_ok else "not_installed",
    "hint": "" if ddgs_ok else "Run: pip install ddgs  (zero-config multi-engine fallback)",
})
```

Update the `ready_tiers` logic so `search` is included even without SearXNG when either fallback is available:
```python
search_ready = (
    (searxng_api_ok and core_deps_ok)
    or (brave_key and core_deps_ok)
    or (ddgs_ok and core_deps_ok)
)
if search_ready:
    ready_tiers.append("search")
```

Add `search_backend` field to doctor output indicating which backend will be used:
```python
search_backend = (
    "searxng" if searxng_api_ok
    else "brave" if brave_key
    else "ddgs"  if ddgs_ok
    else "none"
)
# Include in doctor emit dict:
"search_backend": search_backend,
```

---

## Item 5 — `--max-tokens N` / `--truncate N` on fetch/crawl/extract

**Priority:** ⭐ Agent ergonomics  
**Effort:** S (~1 hour)  
**Rationale:** Agents operating under token budgets have no way to bound the size of returned content. A 50,000-word Wikipedia article will overflow context windows. This is purely post-processing — no change to fetching logic.

**Affected files:**
- `scripts/web.py` (add `--max-tokens` to `fetch`, `crawl`, `extract` subparsers)
- `scripts/_normalize.py` (add `truncated: bool` and `char_count: int` to `WebResult`)
- `scripts/web.py` (apply truncation after handler returns result, before `emit()`)

**Implementation:**

Add to `p_fetch`, `p_crawl`, `p_extract` in `build_parser()`:
```python
parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=0,
                    help="Truncate markdown/text to approximately N tokens (1 token ≈ 4 chars)")
```

Add a shared post-processing step in each command handler, or extract into a helper:
```python
def _apply_token_limit(result: WebResult, max_tokens: int) -> WebResult:
    """Truncate markdown and text to approximately max_tokens tokens."""
    if max_tokens <= 0:
        return result
    char_limit = max_tokens * 4  # rough approximation: 1 token ≈ 4 chars
    result.char_count = len(result.markdown or result.text or "")
    if result.markdown and len(result.markdown) > char_limit:
        result.markdown = result.markdown[:char_limit] + "\n\n[...truncated]"
        result.truncated = True
    if result.text and len(result.text) > char_limit:
        result.text = result.text[:char_limit] + "\n[...truncated]"
        result.truncated = True
    return result
```

Add to `WebResult` in `_normalize.py`:
```python
char_count: int = 0
truncated: bool = False
```

Both fields included in `to_dict()` when truthy.

**Callers:** In `cmd_fetch`, `cmd_crawl`, `cmd_extract`:
```python
result = _apply_token_limit(result, getattr(args, "max_tokens", 0))
emit(result.to_dict(), pretty=args.pretty)
```

> **Note on mutual exclusion with Item 5a (`--chunk-tokens`):** `--max-tokens` and `--chunk-tokens` are mutually exclusive. `--chunk-tokens` takes precedence when both are provided. The handler must enforce this explicitly — see Item 5a "Callers" section for the required conditional.

---

## Item 5a — `fetch --chunk-index I --chunk-count N` paginated content access

**Priority:** ⭐ Agent ergonomics
**Effort:** S (~1.5 hours)
**Gap addressed:** Gap 5 — the review explicitly cites the ability to request "page 2 of 3" as a missing use case. `--max-tokens` (Item 5) is a blunt truncation; this provides structured, deterministic access to any slice of long content.
**Rationale:** An agent can fetch chunk 1 of a long page, decide if it needs to read further, and fetch chunk 2 only if necessary. This maps directly onto how agents should budget context: read incrementally, stop when you have enough.

**Affected files:**
- `scripts/web.py` (add `--chunk-index`, `--chunk-count`, `--chunk-tokens` to `fetch`, `crawl`, `extract`)
- `scripts/_normalize.py` (add `chunk_index`, `chunk_count`, `chunk_tokens` to `WebResult`)

**New flags:**
```python
p_fetch.add_argument("--chunk-tokens", dest="chunk_tokens", type=int, default=0,
                     help="Split content into chunks of ~N tokens each (1 token ≈ 4 chars)")
p_fetch.add_argument("--chunk-index", dest="chunk_index", type=int, default=0,
                     help="Which chunk to return (0-based). Requires --chunk-tokens.")
```

**New `WebResult` fields:**
```python
chunk_index: int = 0
chunk_count: int = 0
chunk_tokens: int = 0
```

**Shared helper (add to `web.py` alongside `_apply_token_limit`):**
```python
def _apply_chunking(result: WebResult, chunk_tokens: int, chunk_index: int) -> WebResult:
    """Return a specific chunk of the content. Sets chunk_count on the result."""
    if chunk_tokens <= 0:
        return result
    char_size = chunk_tokens * 4
    content = result.markdown or result.text or ""
    if not content:
        return result

    # Split on paragraph boundaries where possible, to avoid cutting mid-sentence
    # Fall back to hard split if no paragraph boundary near the chunk boundary
    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= char_size:
            chunks.append(remaining)
            break
        # Find nearest paragraph break before char_size
        boundary = remaining.rfind("\n\n", 0, char_size)
        if boundary == -1 or boundary < char_size // 2:
            boundary = char_size  # hard split
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()

    result.chunk_count = len(chunks)
    result.chunk_tokens = chunk_tokens
    safe_index = max(0, min(chunk_index, len(chunks) - 1))
    result.chunk_index = safe_index

    chunk_content = chunks[safe_index] if chunks else ""
    if result.markdown:
        result.markdown = chunk_content
    if result.text:
        # Approximate: use same chunk boundaries on text
        result.text = chunk_content
    return result
```

**Agent usage pattern:**
```bash
# Fetch chunk 0 — decide if more is needed
web-intel fetch "https://long-article.com" --chunk-tokens 1000

# If agent needs more, fetch chunk 1
web-intel fetch "https://long-article.com" --chunk-tokens 1000 --chunk-index 1
```

The `chunk_count` field in the response tells the agent how many chunks exist total, so it knows when to stop.

**Callers:** In `cmd_fetch`, `cmd_crawl`, `cmd_extract`, replace the simple `_apply_token_limit` call with this mutual-exclusion conditional:
```python
chunk_tokens = getattr(args, "chunk_tokens", 0)
chunk_index  = getattr(args, "chunk_index",  0)
max_tokens   = getattr(args, "max_tokens",   0)

if chunk_tokens > 0:
    # Chunking takes precedence over truncation
    result = _apply_chunking(result, chunk_tokens, chunk_index)
elif max_tokens > 0:
    result = _apply_token_limit(result, max_tokens)
# else: no post-processing, emit as-is

emit(result.to_dict(), pretty=args.pretty)
```

**`doctor` / `SKILL.md` note:** Document that `--chunk-tokens` and `--max-tokens` are mutually exclusive. If both are provided, `--chunk-tokens` takes precedence (enforced by the conditional above).

---

## Item 6 — `fetch --relevant-to "query"` semantic section filter

**Priority:** ⭐ Agent ergonomics  
**Effort:** M (~2.5 hours)  
**Rationale:** The most valuable single feature for research agents. Instead of dumping full page content, return only the paragraphs most relevant to a given question/query. No external API needed — implement with TF-IDF paragraph scoring.

**Affected files:**
- `scripts/web.py` (add `--relevant-to` to `fetch`, `crawl`, `extract`)
- `scripts/_relevance.py` (new file — paragraph scorer)

**New file `scripts/_relevance.py`:**
```python
"""Lightweight paragraph relevance scoring using TF-IDF cosine similarity.
No external dependencies — uses stdlib math only.
"""
from __future__ import annotations
import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b[a-z]{2,}\b', text.lower())


def _tfidf_score(query_tokens: list[str], para_tokens: list[str],
                 doc_freqs: dict[str, int], num_docs: int) -> float:
    if not para_tokens or not query_tokens:
        return 0.0
    para_counts = Counter(para_tokens)
    score = 0.0
    for token in set(query_tokens):
        tf = para_counts.get(token, 0) / len(para_tokens)
        df = doc_freqs.get(token, 0)
        idf = math.log((num_docs + 1) / (df + 1)) + 1
        score += tf * idf
    return score


def filter_relevant_paragraphs(
    markdown: str,
    query: str,
    *,
    top_n: int = 10,
    min_chars: int = 80,
) -> str:
    """Return the top_n most relevant paragraphs from markdown, in original order."""
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', markdown) if len(p.strip()) >= min_chars]
    if not paragraphs:
        return markdown

    query_tokens = _tokenize(query)
    tokenized_paras = [_tokenize(p) for p in paragraphs]

    # Build document frequencies
    doc_freqs: dict[str, int] = Counter()
    for tokens in tokenized_paras:
        for token in set(tokens):
            doc_freqs[token] += 1

    scores = [
        _tfidf_score(query_tokens, tokens, doc_freqs, len(paragraphs))
        for tokens in tokenized_paras
    ]

    # Select top_n by score, preserve original document order
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    selected = sorted([i for i, _ in indexed[:top_n]])
    return "\n\n".join(paragraphs[i] for i in selected)
```

**Changes to `web.py`:**

Add to `p_fetch`, `p_crawl`, `p_extract`:
```python
parser.add_argument("--relevant-to", dest="relevant_to", default="",
                    help="Filter content to paragraphs most relevant to this query/question")
parser.add_argument("--relevant-top", dest="relevant_top", type=int, default=10,
                    help="Number of top paragraphs to include (default: 10)")
```

In each command handler, after getting `result`:
```python
if getattr(args, "relevant_to", "") and result.markdown:
    from _relevance import filter_relevant_paragraphs
    result.markdown = filter_relevant_paragraphs(
        result.markdown, args.relevant_to, top_n=args.relevant_top
    )
    if result.text:
        result.text = filter_relevant_paragraphs(
            result.text, args.relevant_to, top_n=args.relevant_top
        )
```

**Tests:** Unit test with a known paragraph set — verify that paragraphs about "authentication" score higher than paragraphs about "database migrations" for the query "how does auth work".

---

## Item 7 — Enrich search results (date, domain, multi-engine dedup)

**Priority:** ⭐ Data quality  
**Effort:** S (~1 hour)  
**Rationale:** The current search result is minimal: `url, title, snippet, engine, score`. Agents deciding which result to read first have no signal beyond the SearXNG score. Adding `published_at`, `domain`, and `engines` (the list of engines that returned this URL) enables prioritization without fetching.

**Affected files:**
- `scripts/_searxng.py`

**Changes to `_searxng.py`:**

SearXNG already returns `engines` (list of engine names that matched), `category`, and sometimes `publishedDate` in its raw response. These are being dropped.

```python
from urllib.parse import urlparse

def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""

# In the mapped results:
mapped = [
    {
        "url": r.get("url", ""),
        "title": r.get("title", ""),
        "snippet": r.get("content", ""),
        "engine": r.get("engine", ""),           # primary engine
        "engines": r.get("engines", []),          # all engines that matched (dedup signal)
        "score": r.get("score", 0),
        "domain": _extract_domain(r.get("url", "")),
        "published_at": r.get("publishedDate", "") or r.get("published_date", ""),
        "category": r.get("category", ""),
    }
    for r in raw_results
]
```

**Deduplication by URL (not domain):** SearXNG sometimes returns the same URL from multiple engines. Deduplicate before returning, merging `engines` lists:
```python
seen: dict[str, dict] = {}
for r in mapped:
    url = r["url"]
    if url in seen:
        seen[url]["engines"] = list(set(seen[url]["engines"] + r["engines"]))
        seen[url]["score"] = max(seen[url]["score"], r["score"])
    else:
        seen[url] = r
mapped = list(seen.values())[:max_results]
```

Also add `number_of_results` (from SearXNG's `number_of_results` field) to `SearchResult`:
```python
# In SearchResult dataclass
number_of_results: int = 0  # raw estimate from search engine
```

---

## Item 7a — Search result relevance/quality ranking signal

**Priority:** ⭐ Data quality
**Effort:** S (~45 min)
**Gap addressed:** Gap 2 — search results have no quality signal beyond SearXNG's raw score.
**Rationale:** SearXNG's `score` field is an aggregation of engine-specific scores — useful but opaque. The gap explicitly calls out that Exa/Tavily return snippet-level semantic scores. We can produce a lightweight heuristic: a `quality_score` computed from snippet-query term overlap plus number of engines that returned the URL. Zero new dependencies, computed post-search.

**Affected files:**
- `scripts/_searxng.py` (add `quality_score` computation after mapping results)

**Implementation:**

Add `_compute_quality_score()` to `_searxng.py`:
```python
import math
import re

def _compute_quality_score(result: dict, query: str) -> float:
    """
    Heuristic quality score 0.0–1.0 for a search result.
    Combines:
      - snippet/title term overlap with query (0–0.5)
      - number of engines that returned this result (0–0.3)
      - SearXNG score normalized (0–0.2)
    """
    query_terms = set(re.findall(r'\b[a-z]{2,}\b', query.lower()))
    if not query_terms:
        return 0.0

    # Term overlap in title + snippet
    content = (result.get("title", "") + " " + result.get("snippet", "")).lower()
    content_terms = set(re.findall(r'\b[a-z]{2,}\b', content))
    overlap = len(query_terms & content_terms) / len(query_terms)
    overlap_score = min(overlap * 0.5, 0.5)

    # Engine count signal (more engines = more credible)
    engine_count = len(result.get("engines", [result.get("engine", "")]))
    engine_score = min((engine_count - 1) * 0.1, 0.3)

    # Normalized SearXNG score (typically 0–3+, normalize to 0–0.2)
    raw_score = result.get("score", 0)
    score_norm = min(raw_score / 3.0 * 0.2, 0.2)

    return round(overlap_score + engine_score + score_norm, 3)
```

After deduplication, add `quality_score` to each result:
```python
for r in mapped:
    r["quality_score"] = _compute_quality_score(r, query)

# Sort by quality_score descending before returning
mapped.sort(key=lambda r: r["quality_score"], reverse=True)
```

Note: Sorting by `quality_score` replaces SearXNG's default ordering. Add a `--no-rerank` flag to `p_search` if agents want the original ordering:
```python
p_search.add_argument("--no-rerank", action="store_true",
                      help="Preserve SearXNG result order, don't rerank by quality_score")
```

**`SearchResult` change:** `quality_score` lives on each result dict, not on the envelope itself — no dataclass change needed.

> **⚠️ `quality_score` semantics across backends:** For SearXNG results all three components (overlap, engine count, raw score) are meaningful. For fallback backends the components degrade:
> - **Brave API:** `score` field is `relevance_score` from Brave — meaningful. `engines` is `["brave"]` (single engine, no boost). Score breakdown still useful.
> - **DuckDuckGo lite:** `score` is hardcoded `0` and `engines` is `["duckduckgo_lite"]`. Only the term-overlap component fires. `quality_score` reflects query-keyword match in title+snippet only.
> - **StartPage:** `score` is hardcoded `0` and `engines` is `["startpage"]`. Same as DDG — overlap-only signal. `published_at` is populated from the JSON `date` field when present.
> - **Merged DDG+StartPage results:** After `merge_fallback_results`, results from both engines share the same overlap-only signal. The interleaved ordering (DDG1, SP1, DDG2, SP2, ...) already provides implicit diversity; `quality_score` re-ranks within that merged list.
>
> Document this in SKILL.md under the `search` command: "`quality_score` is a heuristic signal. Accuracy is highest with SearXNG (all components active) and lower with fallback backends (overlap-only for DDG and StartPage, partial for Brave)."

---

## Item 8 — `scrape --schema JSON` multi-field structured extraction

**Priority:** ⭐ New capability  
**Effort:** M (~2 hours)  
**Rationale:** Extracting multiple fields from a page in one pass. Current `--selector` only handles one selector per invocation. This is Firecrawl's core value prop, implementable entirely in BS4.

**Affected files:**
- `scripts/web.py` (new `--schema` flag on `scrape`)
- `scripts/_bs4_scrape.py` (new `scrape_schema()` function)

**New CLI signature:**
```bash
web-intel scrape URL --schema '{"title": "h1", "price": ".price", "rating": ".stars", "links": {"selector": "nav a", "attribute": "href", "multiple": true}}'
```

**Schema format:**
```json
{
  "field_name": "css-selector",
  "field_name2": {
    "selector": "css-selector",
    "attribute": "href",
    "multiple": true
  }
}
```

**New function `scrape_schema()` in `_bs4_scrape.py`:**
```python
def scrape_schema(html: str, schema: dict, *, url: str = "") -> WebResult:
    """Extract multiple fields from HTML using a JSON schema of CSS selectors."""
    from bs4 import BeautifulSoup
    import json as _json

    with Timer() as t:
        try:
            soup = BeautifulSoup(html, "lxml")
            extracted: dict[str, Any] = {}

            for field, spec in schema.items():
                if isinstance(spec, str):
                    # Simple: field -> selector string, extract text
                    el = soup.select_one(spec)
                    extracted[field] = el.get_text(strip=True) if el else None
                elif isinstance(spec, dict):
                    selector = spec.get("selector", "")
                    attribute = spec.get("attribute")
                    multiple = spec.get("multiple", False)
                    elements = soup.select(selector) if multiple else [soup.select_one(selector)]
                    elements = [e for e in elements if e is not None]
                    results_for_field = []
                    for el in elements:
                        if attribute:
                            results_for_field.append(el.get(attribute, ""))
                        else:
                            results_for_field.append(el.get_text(strip=True))
                    extracted[field] = results_for_field if multiple else (results_for_field[0] if results_for_field else None)
        except Exception as exc:
            return WebResult(url=url, status="failed", extract_mode="bs4",
                             error=f"Schema extraction failed: {exc}", timing_ms=t.elapsed_ms)

    # Represent structured data in text as pretty JSON, in markdown as a code block
    as_json = _json.dumps(extracted, ensure_ascii=False, indent=2)
    return WebResult(
        url=url,
        text=as_json,
        markdown=f"```json\n{as_json}\n```",
        extract_mode="bs4",
        confidence=0.9 if any(v is not None for v in extracted.values()) else 0.0,
        timing_ms=t.elapsed_ms,
    )
```

**In `web.py`:**
```python
p_scrape.add_argument("--schema", default="",
                      help='JSON schema: {"field": "css-selector", ...}')
```

In `cmd_scrape()`, add a branch before the existing `--table`/`--list`/`--selector` checks:
```python
elif args.schema:
    import json as _json
    try:
        schema = _json.loads(args.schema)
    except _json.JSONDecodeError as exc:
        emit_error("scrape", f"Invalid --schema JSON: {exc}", pretty=args.pretty)
        return
    result = scrape_schema(html, schema, url=args.url)
```

---

## Item 9 — Enrich `discover` results with metadata

**Priority:** ⭐ / 🔵 Data quality  
**Effort:** S (~1.5 hours)  
**Rationale:** `discover` returns a flat `urls[]` list. Sitemaps include `lastmod`, `changefreq`, and `priority` per URL. Trafilatura's `sitemap_search` discards these. A minimal sitemap parser can extract them.

**Affected files:**
- `scripts/_trafilatura_extract.py`
- `scripts/_normalize.py` (add `url_entries` to `DiscoverResult`)

**`DiscoverResult` change:**
```python
@dataclass
class DiscoverResult:
    ...
    urls: list[str] = field(default_factory=list)           # backward compat: flat list
    url_entries: list[dict] = field(default_factory=list)   # enriched: [{url, title, last_modified, priority, depth}]
```

**New `discover_sitemap_enriched()` function:**

> **⚠️ Do not use `_httpx_fetch.fetch()` here.** That helper pipes the response through trafilatura's extraction pipeline, which mangles XML into prose. Use a raw `httpx.get()` instead so `ET.fromstring()` receives the actual XML bytes.

```python
def discover_sitemap_enriched(url: str, *, max_urls: int = 100) -> DiscoverResult:
    """Parse sitemap XML directly to extract URL metadata."""
    import httpx
    import xml.etree.ElementTree as ET
    from urllib.parse import urljoin

    # Common sitemap locations
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
            root = ET.fromstring(resp.content)  # bytes → ET; avoids encoding issues
            for url_el in root.findall(".//sm:url", ns)[:max_urls]:
                loc = url_el.findtext("sm:loc", namespaces=ns) or ""
                if not loc:
                    continue
                entry: dict = {"url": loc}
                for field in ("lastmod", "changefreq", "priority"):
                    val = url_el.findtext(f"sm:{field}", namespaces=ns)
                    if val:
                        entry[field] = val
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
```

---

## Item 9a — `discover --mode crawl` BFS depth tracking

**Priority:** 🔵 Data quality
**Effort:** S (~1.5 hours)
**Gap addressed:** Gap 4 — depth is explicitly mentioned in the gap but was not addressed by Item 9 (which only covers sitemap metadata). Crawl-mode discovery uses Trafilatura's `focused_crawler` which does not expose depth. This item replaces it with a minimal BFS implementation that tracks depth per URL.

**Affected files:**
- `scripts/_trafilatura_extract.py` (`discover_crawl` function)
- `scripts/_normalize.py` (`url_entries` field already added by Item 9)

**Replace `discover_crawl()` BFS logic:**

The current implementation calls `trafilatura.spider.focused_crawler()`, which is a black box that returns a flat `known` set with no depth info. Replace it with an explicit BFS loop using httpx + BS4 link extraction.

> **⚠️ Do not use `trafilatura.extract_metadata()` for link extraction.** `extract_metadata()` returns a `Metadata` object (title, author, date, etc.) — it does not return outbound links. The original code assigned its return value to `links` but never used it; the variable was dead code. Link extraction is done exclusively via BS4 `<a href>` parsing.

```python
def discover_crawl(
    url: str,
    *,
    max_urls: int = 100,
    language: Optional[str] = None,
) -> DiscoverResult:
    """BFS crawl from root URL, tracking depth per discovered URL.

    Link extraction uses BS4 <a href> parsing only.
    For sites >500 URLs, consider the async Trafilatura spider;
    this BFS is intentionally simple.
    """
    from _httpx_fetch import fetch
    from urllib.parse import urljoin, urlparse

    base_domain = urlparse(url).netloc
    visited: set[str] = set()
    # queue entries: (url, depth)
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

            # Extract outbound links via BS4
            hrefs: list[str] = []
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                hrefs = [
                    urljoin(current_url, a.get("href", ""))
                    for a in soup.find_all("a", href=True)
                ]
            except Exception:
                pass  # no links found for this page; continue BFS with what we have

            entries.append({"url": current_url, "depth": depth})

            for href in hrefs:
                parsed = urlparse(href)
                # Stay on same domain, only http/https
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
```

**Depth field in `url_entries`:**
```json
{"url": "https://docs.example.com/api/auth", "depth": 2, "lastmod": "2026-01-10"}
```

Depth 0 = the root URL passed to `discover`. Depth 1 = directly linked from root. Etc.

---

## Item 10 — `fetch-batch` command (parallel URL list from stdin)

**Priority:** ⭐ Performance  
**Effort:** M (~2.5 hours)  
**Rationale:** Agents processing many URLs (from search results or discover output) must do it via shell loops, serially, with `sleep`. A native batch command enables true parallelism with proper rate-limiting.

**Affected files:**
- `scripts/web.py` (new `fetch-batch` subcommand)

**CLI signature:**
```bash
# From stdin (newline-separated URLs)
echo -e "https://a.com\nhttps://b.com" | web-intel fetch-batch --concurrency 3

# From a file
web-intel fetch-batch --url-file urls.txt --concurrency 5 --max-tokens 2000

# From discover output
web-intel discover https://docs.example.com | jq -r '.urls[:20][]' | web-intel fetch-batch
```

**Output:** NDJSON (one JSON object per line, one per URL), so downstream tools can process as results arrive:
```json
{"url": "https://a.com", "status": "ok", "title": "...", "markdown": "...", "timing_ms": 430}
{"url": "https://b.com", "status": "ok", "title": "...", "markdown": "...", "timing_ms": 510}
```

**Implementation sketch:**
```python
def cmd_fetch_batch(args: argparse.Namespace) -> None:
    import asyncio
    from _trafilatura_extract import fetch_and_extract

    # Read URLs
    if args.url_file:
        urls = Path(args.url_file).read_text().splitlines()
    else:
        urls = sys.stdin.read().splitlines()
    urls = [u.strip() for u in urls if u.strip()]

    if not urls:
        emit_error("fetch-batch", "No URLs provided", pretty=args.pretty)
        return

    sem = asyncio.Semaphore(args.concurrency)

    async def _fetch_one(url: str) -> None:
        async with sem:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: fetch_and_extract(url, timeout=args.timeout)
            )
            result.command = "fetch-batch"
            if args.max_tokens:
                result = _apply_token_limit(result, args.max_tokens)
            # NDJSON: one line per result, emitted as results arrive
            emit(result.to_dict(), pretty=False)

    async def _run():
        await asyncio.gather(*[_fetch_one(u) for u in urls])

    asyncio.run(_run())
```

Note: When `--pretty` is used with `fetch-batch`, it should still emit one JSON object per line (not a JSON array), just with indentation stripped. NDJSON is the contract.

**Parser:**
```python
p_batch = sub.add_parser("fetch-batch", help="Batch fetch URLs from stdin or file")
p_batch.add_argument("--url-file", dest="url_file", default="")
p_batch.add_argument("--concurrency", type=int, default=3)
p_batch.add_argument("--timeout", type=int, default=20)
p_batch.add_argument("--max-tokens", dest="max_tokens", type=int, default=0)
p_batch.add_argument("--include-tables", action="store_true")
p_batch.add_argument("--include-links", action="store_true")
p_batch.add_argument("--pretty", action="store_true")
p_batch.set_defaults(func=cmd_fetch_batch)
```

---

## Item 8a — Rate-limiting: document `fetch-batch` as the only safe parallel path

**Priority:** 🔵 Reliability
**Effort:** XS (~20 min)
**Gap addressed:** Gap 8 — `MAX_CONCURRENT_FETCHES=5` is defined but unenforced. Nothing prevents an agent from running `for url in ...; do web-intel fetch $url &; done`, which bypasses all limits. A process-level lock for single `fetch` invocations would require IPC and is disproportionately complex. The pragmatic fix is:

1. **Enforce the semaphore inside `fetch-batch`** (already specified in Item 10's `asyncio.Semaphore(args.concurrency)`).
2. **Make the SKILL.md rate-limit note authoritative** — change the current vague "Rate-limit all requests. Max 5 concurrent fetches per domain." to an explicit contract:

```markdown
> **Concurrency:** For parallel URL fetching, always use `fetch-batch --concurrency N`. 
> Single `fetch` calls in shell loops are not rate-limited and may trigger target server rate limits or bans.
> `MAX_CONCURRENT_FETCHES` is enforced by `fetch-batch` only.
```

3. **Add a `--domain-delay` flag to `fetch-batch`** to enforce per-domain minimum delay (the gap called out "max 5 concurrent fetches per domain" specifically):
```python
p_batch.add_argument("--domain-delay", dest="domain_delay", type=float, default=0.0,
                     help="Minimum seconds between requests to the same domain (default: 0, recommended: 1.0)")
```

Implementation: maintain a `last_request_time: dict[str, float]` keyed by domain inside `cmd_fetch_batch`. Before each fetch, check the last request time for that domain and `await asyncio.sleep()` the remaining delay if needed.

```python
from urllib.parse import urlparse
import time

domain_last: dict[str, float] = {}
# domain_last is a plain dict mutated inside async coroutines.
# This is safe: asyncio runs on a single OS thread, so there is no
# concurrent dict mutation. No lock is needed.

async def _fetch_one(url: str) -> None:
    async with sem:
        domain = urlparse(url).netloc
        if args.domain_delay > 0 and domain in domain_last:
            wait = args.domain_delay - (time.monotonic() - domain_last[domain])
            if wait > 0:
                await asyncio.sleep(wait)
        domain_last[domain] = time.monotonic()
        # ... rest of fetch logic
```

This is the only place in the codebase where per-domain rate limiting is actually enforced.

---

## Item 11 — Computed confidence score (content density ratio)

**Priority:** 🔵 Quality signal  
**Effort:** S (~30 min)  
**Rationale:** Current confidence values are hardcoded constants (`0.85`, `0.9`, `0.95`). A signal computed from the actual content gives agents a better hint about extraction quality.

**Formula:**
```
content_density = len(extracted_text) / max(len(raw_html), 1)
confidence = min(content_density * 5, 1.0)   # normalize: ~20% density = 1.0
```

This is imperfect but directionally correct: a page where Trafilatura extracted 10 chars from 50,000 chars of HTML has lower quality than one where 5,000 chars were extracted from 20,000.

**Affected files:**
- `scripts/_trafilatura_extract.py` (pass `html` length to `extract_from_html`)
- `scripts/_bs4_scrape.py` (similar adjustment)

**Change in `_trafilatura_extract.py`:**
```python
def extract_from_html(html: str, ...) -> WebResult:
    ...
    html_len = len(html)
    extracted_len = len(extracted or "")
    confidence = min((extracted_len / max(html_len, 1)) * 5, 1.0) if extracted_len else 0.0
    ...
    return WebResult(..., confidence=confidence, ...)
```

---

## Item 12 — `fetch --diff` change detection

**Priority:** 🔵 Monitoring  
**Effort:** M (~2.5 hours)  
**Rationale:** Monitoring agents need to know if a page has changed since last visit. Store a lightweight cache of previous content hashes and return diff metadata when re-fetching.

**Affected files:**
- `scripts/web.py` (add `--diff` to `fetch`)
- `scripts/_page_cache.py` (new file — simple SHA256 content cache)
- `scripts/_normalize.py` (add `changed`, `previous_hash`, `current_hash` to `WebResult`)

**Cache format:** Simple JSON file at `.deps_cache/page_cache.json`:
```json
{
  "https://example.com": {
    "hash": "sha256:abc123...",
    "fetched_at": "2026-04-26T10:00:00Z",
    "title": "Example Domain"
  }
}
```

**New `WebResult` fields:**
```python
current_hash: str = ""
previous_hash: str = ""
changed: Optional[bool] = None   # None = first visit, True/False = compared to cache
```

**`--diff` behavior:**
- Without `--diff`: normal fetch, no cache interaction.
- With `--diff`: fetch, compute hash of markdown content, compare to cached hash. Set `changed=True/False`, update cache.
- `changed=None` means no previous cache entry.

**Implementation in `_page_cache.py`:**
```python
import hashlib, json
from pathlib import Path
from datetime import datetime, timezone

_CACHE_FILE = Path(__file__).resolve().parent.parent / ".deps_cache" / "page_cache.json"

def _load() -> dict: ...
def _save(cache: dict) -> None: ...

def check_and_update(url: str, content: str, title: str = "") -> tuple[Optional[bool], str, str]:
    """Returns (changed, previous_hash, current_hash). changed=None if first visit."""
    current_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]
    cache = _load()
    entry = cache.get(url)
    previous_hash = entry["hash"] if entry else ""
    changed = None if not entry else (current_hash != previous_hash)
    cache[url] = {"hash": current_hash, "fetched_at": datetime.now(timezone.utc).isoformat(), "title": title}
    _save(cache)
    return changed, previous_hash, current_hash
```

---

## Item 13 — Unit test suite for pure-Python modules

**Priority:** 🔵 Correctness  
**Effort:** M (~4 hours, updated from 3 to account for added coverage)  
**Rationale:** The entire parsing layer (`_normalize.py`, `_bs4_scrape.py`, `_deps.py`, `_relevance.py`, `_searxng.py` pure functions, `_page_cache.py`) is pure Python with no network dependencies. Currently untested. These break silently under refactoring.

**Affected files:**
- `tests/test_normalize.py` (new)
- `tests/test_bs4_scrape.py` (new)
- `tests/test_deps.py` (new)
- `tests/test_relevance.py` (new — **depends on Item 6 being merged first**; must not be included in the initial test suite PR)
- `tests/test_searxng.py` (new — covers pure functions added by Items 7 and 7a; no SearXNG service required)
- `tests/test_page_cache.py` (new — **depends on Item 12 being merged first**; covers `_page_cache.py` pure functions)

**Coverage targets per module:**

`test_normalize.py`:
- `WebResult.to_dict()` omits empty string fields
- `WebResult.to_dict()` preserves `status` and `command` even when empty
- `WebResult.to_dict()` never emits the `html` field (internal-only)
- `SearchResult.to_dict()` omits `error` when not set
- `Timer` measures elapsed time correctly
- `emit_error()` writes valid JSON to stdout

`test_bs4_scrape.py`:
- `scrape_tables()` extracts a known `<table>` into correct 3D array
- `scrape_tables()` returns `status=partial` when no tables found
- `scrape_selector()` returns matching text
- `scrape_selector()` returns `status=partial` when selector matches nothing
- `scrape_lists()` correctly extracts nested `<ul>/<ol>` items
- Markdown table output for `scrape_tables()` is valid markdown
- `scrape_schema()` extracts multiple fields from known HTML (depends on Item 8)
- `scrape_schema()` sets `extracted[field]=None` for selectors that match nothing

`test_deps.py`:
- `_import_name()` maps pip names to import names correctly
- `_missing()` detects a fake uninstalled package
- `_stamp_path()` is deterministic for the same dep list

`test_relevance.py` (**add only after Item 6 is merged**):
- Higher-scoring paragraphs returned for relevant query
- Short paragraphs below `min_chars` excluded
- Empty input returns empty output without crashing

`test_searxng.py` (covers Items 7 and 7a pure functions — no SearXNG service needed):
- `_extract_domain("https://www.example.com/path")` → `"example.com"`
- `_extract_domain("")` → `""` without raising
- Dedup logic: two results with the same URL merge `engines` lists and take max `score`
- `_compute_quality_score` returns higher score for a result whose title+snippet contains all query terms
- `_compute_quality_score` returns `0.0` for empty `query_terms`
- Multi-engine result scores higher than single-engine result (engine count signal)

`test_page_cache.py` (**add only after Item 12 is merged**):
- `check_and_update()` returns `changed=None` on first call for a URL
- `check_and_update()` returns `changed=False` when content is identical on second call
- `check_and_update()` returns `changed=True` when content differs on second call
- `current_hash` format: starts with `"sha256:"`
- Cache file is created at the expected path after first call

---

## Item 14 — `--wait-for-text` on static fetch

**Priority:** 🔵 Reliability  
**Effort:** S (~1 hour)  
**Rationale:** Some pages that serve static HTML have content that changes after initial load (streaming, progressive hydration patterns in SSR frameworks). A simple retry-until-content-present loop using only httpx can catch these without the full browser overhead.

> **⚠️ Scope: httpx path only.** `--wait-for-text` retries the httpx fetch (`fetch_and_extract`). It does **not** retry `crawl` (Crawl4AI) invocations. Pages that genuinely require JavaScript execution to render content should use `web-intel crawl` instead — retrying httpx on a JS-gated page will never succeed. Document this distinction in `--wait-for-text`'s help string.

**Affected files:**
- `scripts/web.py` (add `--wait-for-text` to `fetch`)
- `scripts/_trafilatura_extract.py` (`fetch_and_extract` gains retry logic)

**New flag:**
```python
p_fetch.add_argument("--wait-for-text", dest="wait_for_text", default="",
                     help="Retry httpx fetch until this text appears in extracted content (max 3 retries). "
                          "Static pages only — does not work for JS-gated content; use 'crawl' for those.")
p_fetch.add_argument("--wait-for-retries", dest="wait_for_retries", type=int, default=3)
p_fetch.add_argument("--wait-for-delay", dest="wait_for_delay", type=float, default=2.0,
                     help="Seconds to wait between retries (default: 2.0)")
```

**Logic in `cmd_fetch()`:**
```python
if args.wait_for_text and result.status == "ok":
    import time
    target = args.wait_for_text.lower()
    for attempt in range(args.wait_for_retries):
        content = (result.markdown or result.text or "").lower()
        if target in content:
            break
        time.sleep(args.wait_for_delay)
        result = fetch_and_extract(args.url, ...)
```

---

## Item 15 — `char_count` + `truncated` fields in envelope

**Priority:** ⚪ Introspection
**Effort:** XS (~15 min)
**Gap addressed:** Gap 5 (sub-item of Item 5).
**Rationale:** Covered by Item 5 implementation — `char_count` and `truncated` are added to `WebResult` as part of `--max-tokens` support. No additional work needed if Item 5 is implemented.

---

## Implementation Order (Recommended)

### Phase 1 — Bug Fixes & Quick Wins (1–2 days)

Addresses Gaps 6, 7, 2, 8 (partially). No new features, all correctness and signal improvements.

1. **Item 1** — Fix `get_raw_html` HTML/markdown confusion (Gap 7, ~30 min)
2. **Item 2** — Eliminate triple Trafilatura pass (Gap 6, ~45 min)
3. **Item 7** — Enrich search results with date/domain/engines/dedup (Gap 2, ~1 hr)
4. **Item 7a** — Search result `quality_score` ranking (Gap 2, ~45 min)
5. **Item 11** — Computed confidence score, replace hardcoded constants (~30 min)

### Phase 2 — Gap Closures: Token Budget & Search Fallback (2–3 days)

Addresses Gaps 1 and 5 — the two most user-impactful gaps.

6. **Item 4** — Search fallback chain: SearXNG → Brave → DDG+StartPage merged (Gap 1, ~4 hrs)
7. **Item 4a** — `doctor` reports fallback readiness + `search_backend` field (Gap 1, ~30 min)
8. **Item 5** — `--max-tokens N` truncation (Gap 5, ~1 hr)
9. **Item 5a** — `--chunk-tokens / --chunk-index` paginated access (Gap 5, ~1.5 hrs)
10. **Item 6** — `fetch --relevant-to "query"` semantic filtering (Gap 5, ~2.5 hrs)
11. **Item 15** — `char_count` + `truncated` envelope fields (Gap 5, ~15 min)

### Phase 3 — Gap Closures: Scraping, Discovery, Batching (2–3 days)

Addresses Gaps 3, 4, and 8.

12. **Item 8** — `scrape --schema JSON` multi-field extraction (Gap 3, ~2 hrs)
13. **Item 9** — Enrich `discover` sitemap results with metadata (Gap 4, ~1.5 hrs)
14. **Item 9a** — `discover --mode crawl` BFS depth tracking (Gap 4, ~1.5 hrs)
15. **Item 10** — `fetch-batch` command with semaphore + NDJSON output (Gap 8, ~2.5 hrs)
16. **Item 8a** — `--domain-delay` on `fetch-batch`, document rate-limiting contract (Gap 8, ~20 min)

### Phase 4 — Enhancements & Quality (2–3 days)

Addresses Gap 9 + pure enhancements not mapped to gaps.

17. **Item 3** — `search --fetch-top N` one-shot pipeline (enhancement, ~3 hrs)
18. **Item 13** — Unit test suite for pure-python modules (Gap 9, ~3 hrs)
19. **Item 14** — `--wait-for-text` retry on static fetch (enhancement, ~1 hr)
20. **Item 12** — `fetch --diff` change detection (enhancement, ~2.5 hrs)

---

## Cross-Cutting Concerns

### Backward compatibility
All changes are additive. New flags default to current behavior (e.g., `--max-tokens 0` = no truncation, `--chunk-tokens 0` = no chunking, `--domain-delay 0` = no delay). Existing `to_dict()` filtering ensures new fields are emitted only when non-default.

### `_COMMAND_DEPS` maintenance
- Item 4 (`_search_fallback.py`): DDG and StartPage fallbacks both use `bs4` — **add `bs4` to `_COMMAND_DEPS["search"]` in `_deps.py`**. This is a required change in the Item 4 affected files, not optional.
- Item 5a / Item 6 (`_relevance.py`): zero new deps (stdlib only).
- Item 3 (`--fetch-top`): when flag is set, call `ensure_deps("fetch")` in `main()` before dispatch.
- Item 9a (BFS crawl): uses `bs4` + `httpx` already in `CORE_DEPS`.

### `doctor` output changes
- Item 4a adds: `search_fallback_brave`, `search_fallback_ddg`, `search_fallback_startpage` checks, `search_backend` top-level field. `ready_commands` includes `search` when any fallback is reachable.
- `ready_commands` logic must be updated so `search` appears when any fallback is available.

### SKILL.md updates required after each phase
- Phase 1: Update `## Commands` → `search` to note enriched result fields.
- Phase 2: Add `search` fallback behavior note (SearXNG → Brave → DDG+StartPage merged); add `--max-tokens`, `--chunk-tokens`, `--relevant-to` to `fetch`/`crawl`/`extract` command docs; update routing table.
- Phase 3: Add `scrape --schema` to `## Commands`; update `discover` docs; add `fetch-batch` as new command; update rate-limit note to reference `fetch-batch`.
- Phase 4: Add `search --fetch-top` to `## Commands`; add `--diff` to `fetch`.

### References folder updates
- Phase 1: Update `output-schema.md` — enriched search result fields.
- Phase 2: Update `routing-guide.md` — search fallback chain; `--relevant-to` guidance; chunking patterns. Update `advanced-patterns.md` — token budget patterns.
- Phase 3: Update `output-schema.md` — `scrape --schema` output, `discover url_entries`, `fetch-batch` NDJSON. Update `routing-guide.md` — when to use `fetch-batch` vs shell loop.
- Phase 4: Update `advanced-patterns.md` — `--fetch-top` one-shot pattern. Add `references/caching.md` for `--diff` cache format.

---

## File Change Summary

| File | Items | Change Type |
|------|-------|-------------|
| `scripts/_normalize.py` | 1, 5, 5a, 9, 12 | Add fields to `WebResult`, `DiscoverResult` |
| `scripts/_trafilatura_extract.py` | 2, 9a, 11, 14 | Refactor extraction passes; BFS crawl; confidence; retry |
| `scripts/_crawl4ai_crawl.py` | 1 | Fix `get_raw_html`, populate `html` field |
| `scripts/_searxng.py` | 7, 7a | Enrich result fields, dedup, `quality_score` |
| `scripts/_bs4_scrape.py` | 8 | Add `scrape_schema()` |
| `scripts/web.py` | 3, 4, 4a, 5, 5a, 6, 8, 8a, 10, 14 | New flags, commands, fallback logic, chunking, rate-limit |
| `scripts/_search_fallback.py` | 4 | New file — DDG lite + Brave API search |
| `scripts/_relevance.py` | 6 | New file — TF-IDF paragraph scorer |
| `scripts/_page_cache.py` | 12 | New file — SHA256 content cache for `--diff` |
| `tests/test_normalize.py` | 13 | New file |
| `tests/test_bs4_scrape.py` | 13 | New file |
| `tests/test_deps.py` | 13 | New file |
| `tests/test_relevance.py` | 13 | New file (after Item 6) |
| `tests/test_searxng.py` | 7, 7a, 13 | New file — `_extract_domain`, dedup, `_compute_quality_score` unit tests |
| `tests/test_page_cache.py` | 12, 13 | New file (after Item 12) — `_page_cache.py` pure function tests |
| `SKILL.md` | All phases | Documentation updates per phase schedule above |
| `references/routing-guide.md` | 4, 6, 8a | Search fallback; `--relevant-to`; rate-limit contract |
| `references/advanced-patterns.md` | 3, 5a, 10 | One-shot; chunking; batch patterns |
| `references/output-schema.md` | 5, 5a, 7, 8, 9, 12 | New envelope fields across commands |
| `.env.example` | 4 | Add `BRAVE_API_KEY` |
