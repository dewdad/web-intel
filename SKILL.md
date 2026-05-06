---
name: web-intel
description: >
  Web search, crawling, scraping, and content extraction for AI agents.
  Routes tasks to SearXNG, httpx, Trafilatura, BeautifulSoup, or Crawl4AI
  based on content type and page complexity.

  Use when: researching topics, fetching web pages, scraping structured data,
  crawling JS-heavy sites, or extracting content from URLs.
metadata:
  version: "0.2.0"
  tags: "web, search, scraping, crawling, research"
  requires-python: "httpx, trafilatura, beautifulsoup4, lxml, ddgs, crawl4ai"
  requires-bins: "python3"
---

# Web Intel

> **JSON output only.** All commands emit JSON to stdout, logs to stderr.

> **Concurrency:** For parallel URL fetching, always use `fetch-batch --concurrency N`.
> Single `fetch` calls in shell loops are not rate-limited and may trigger target server rate limits.
> `MAX_CONCURRENT_FETCHES` is enforced by `fetch-batch` only.

## Path Resolution

```bash
$SKILL_DIR/bin/web-intel <command> [OPTIONS]
python3 $SKILL_DIR/scripts/web.py <command> [OPTIONS]
```

`$SKILL_DIR` is the skill's install directory (e.g., `~/.config/opencode/skills/web-intel`).

## Plug-and-Play Setup

**Tier 1 — Zero setup (works immediately):** `fetch`, `extract`, `discover`, `scrape`, `fetch-batch`
Python deps auto-install on first run. No Docker needed.

```bash
$SKILL_DIR/bin/web-intel fetch "https://example.com" --pretty
```

**Tier 2 — Docker preferred, but not required:** `search`

```bash
$SKILL_DIR/bin/web-intel setup --pretty           # auto-starts SearXNG
$SKILL_DIR/bin/web-intel search "query" --pretty
```

Search fallback chain: **SearXNG → Brave Search API (if BRAVE_API_KEY set) → [ddgs](https://github.com/deedy5/ddgs) (zero-config)**. Search works even without Docker via ddgs.

**Tier 3 — Needs Crawl4AI browser:** `crawl`, `fetch` fallback

```bash
$SKILL_DIR/bin/web-intel setup --tier all --pretty
$SKILL_DIR/bin/web-intel crawl "https://spa.example.com" --pretty
```

## Diagnostic Commands

```bash
$SKILL_DIR/bin/web-intel doctor --pretty   # check all deps, services, and search backends
$SKILL_DIR/bin/web-intel setup --pretty    # auto-fix: install deps, start SearXNG, create .env
$SKILL_DIR/bin/web-intel setup --clear-cache --pretty  # clear dep-stamp cache and page-diff cache
```

`doctor` returns JSON with `ready_commands`, `search_backend` (which backend will be used), and per-dependency `checks[]`.

## Commands

### `search` — Web search

```bash
$SKILL_DIR/bin/web-intel search "query" [--engines google,brave] [--categories general] [--language en]
  [--time-range week] [--max-results 10] [--no-rerank] [--no-fallback]
  [--mode fast|deep]
  [--fetch-top N] [--fetch-concurrency 3] [--fetch-timeout 20] [--no-fit]
  [--no-enrich] [--enrich-concurrency 5] [--enrich-timeout 8]
  [--no-cite]
```

- `--fetch-top N`: Fetch and extract full content from the top N results (one-shot pipeline). Also backfills `published_at`/`authors` from fetched content for free.
- `--no-rerank`: Preserve SearXNG result ordering instead of reranking by `quality_score`.
- `--no-fallback`: Fail immediately if SearXNG unavailable (skip ddgs/Brave fallbacks).
- `--no-enrich`: Skip head-fetch enrichment for missing `published_at`/`authors`. Faster; sourcing may be incomplete.
- `--no-cite`: Omit `citations[]` array and `citation_index` from output.
- `--mode fast`: Disable enrichment/citations, limit to 5 results for low-latency pipelines.
- `--mode deep`: Enable enrichment + citations + `--fetch-top 3` + 10 results for deep research.
- `--no-fit`: When using `--fetch-top`, skip `fit_markdown` noise pruning on fetched content (default: pruning enabled).
- `--enrich-concurrency N`: Max concurrent enrichment head-fetches (default: 5).
- `--enrich-timeout N`: Per-request enrichment timeout in seconds (default: 8).

Result fields: `url`, `title`, `snippet`, `engine`, `engines[]`, `score`, `domain`, `published_at`, `authors`, `quality_score`, `category`, `citation_index`, `meta_enriched[]`, `meta_source`.

Top-level: `citations[]` — always present (unless `--no-cite`), one entry per result:
`"[N] Title by Author — domain (YYYY-MM-DD) url"` or `(date unknown)` when unavailable.

`quality_score` accuracy: highest with SearXNG (all components active), lower with fallback backends (overlap-only for ddgs).

`backend`: `"searxng"` | `"brave"` | `"ddgs"` — which provider handled the query. Agents can branch: `if backend == "ddgs": ignore quality_score`.

### `fetch` — Fast static page fetch + extraction

```bash
$SKILL_DIR/bin/web-intel fetch URL [--include-tables] [--include-links] [--favor-precision|--favor-recall] [--output-format markdown] [--timeout 30] [--max-tokens N] [--chunk-tokens N] [--chunk-index I] [--relevant-to "query"] [--relevant-top 10] [--wait-for-text "text"] [--diff] [--no-cache]
```

- `--max-tokens N`: Truncate output to approximately N tokens (1 token ≈ 4 chars). Adds `truncated=true` and `char_count` when truncated.
- `--chunk-tokens N`: Split content into chunks of ~N tokens. Returns chunk 0 by default. Use `--chunk-index I` to access other chunks. Response includes `chunk_count` (total chunks) and `chunk_index`.
- `--relevant-to "query"`: Filter content to the most relevant paragraphs using TF-IDF scoring. Use `--relevant-top N` (default 10) to control how many paragraphs to return.
- `--wait-for-text "text"`: Retry httpx fetch until this text appears in the extracted content (max 3 retries, 2s delay). **Static pages only** — does not work for JS-gated content; use `crawl` instead.
- `--diff`: Compare content hash to cached version. Response includes `changed` (null=first visit, true/false), `current_hash`, `previous_hash`.
- `--no-cache`: Skip reading and writing the content diff cache for this request. Use in agent loops to force a fresh fetch without storing results.

`--chunk-tokens` and `--max-tokens` are mutually exclusive; `--chunk-tokens` takes precedence.

### `crawl` — Dynamic/JS page crawl (browser, requires Crawl4AI)

```bash
$SKILL_DIR/bin/web-intel crawl URL [--wait-for CSS] [--execute-js CODE] [--screenshot] [--pdf] [--timeout 60] [--docker] [--max-tokens N] [--chunk-tokens N] [--chunk-index I] [--relevant-to "query"]
```

### `scrape` — Structured data extraction

```bash
$SKILL_DIR/bin/web-intel scrape URL --selector CSS [--attribute href]
$SKILL_DIR/bin/web-intel scrape URL --table
$SKILL_DIR/bin/web-intel scrape URL --list
$SKILL_DIR/bin/web-intel scrape URL --schema '{"title": "h1", "price": ".price", "links": {"selector": "nav a", "attribute": "href", "multiple": true}}'
```

`--schema`: Extract multiple fields in one pass. Field spec can be a CSS selector string (extracts text) or a dict with `selector`, `attribute`, and `multiple` keys.

### `extract` — Content extraction from local HTML

```bash
$SKILL_DIR/bin/web-intel extract --html-file PATH [--url URL] [--include-tables] [--output-format markdown] [--max-tokens N] [--chunk-tokens N] [--relevant-to "query"]
echo "<html>..." | $SKILL_DIR/bin/web-intel extract --stdin
```

### `fetch-batch` — Parallel batch URL fetching

```bash
echo -e "https://a.com\nhttps://b.com" | $SKILL_DIR/bin/web-intel fetch-batch [--concurrency 3] [--domain-delay 1.0] [--max-tokens 2000] [--json-array]
$SKILL_DIR/bin/web-intel fetch-batch --url-file urls.txt --concurrency 5

$SKILL_DIR/bin/web-intel discover https://docs.example.com | jq -r '.urls[:20][]' | $SKILL_DIR/bin/web-intel fetch-batch
```

Output: NDJSON (one JSON object per line per URL). Use `--domain-delay 1.0` to enforce per-domain rate limiting.
- `--json-array`: Output a JSON array instead of NDJSON. Use when batch results must be parsed with `json.loads()` alongside single-command results.

### `discover` — Site URL discovery

```bash
$SKILL_DIR/bin/web-intel discover URL [--mode sitemap|crawl|both] [--max-urls 100] [--enriched]
```

- `--enriched`: Parse sitemap XML directly for `lastmod`, `changefreq`, `priority` metadata. Adds `url_entries[]` to response.
- `--mode crawl`: BFS crawl that tracks `depth` per URL (depth 0 = root URL). Adds `url_entries[{url, depth}]`.

## Routing Guide

| Task | Command | Tier | Why |
|------|---------|------|-----|
| Research a topic | `search` | 1-2 | Falls back to ddgs if no Docker |
| Research + read top results | `search --fetch-top 3` | 1-2 | One-shot pipeline |
| Fast search pipeline | `search --mode fast` | 1-2 | Disables enrichment, 5 results, low latency |
| Deep research | `search --mode deep` | 1-2 | Enrichment + fetch-top 3 + 10 results |
| Read article/blog/docs | `fetch` | 1 | Fast httpx + Trafilatura |
| Long article, need section | `fetch --relevant-to "query"` | 1 | TF-IDF paragraph filter |
| Long article, paginated | `fetch --chunk-tokens 1000` | 1 | Return one chunk at a time |
| JS-heavy SPA | `crawl` | 3 | Browser rendering |
| Extract data table (static) | `scrape --table` | 1 | BS4 preserves table structure |
| Extract multiple fields | `scrape --schema {...}` | 1 | One-pass multi-field extraction |
| Process many URLs | `fetch-batch` | 1 | Rate-limited parallel fetch |
| Find all pages on site | `discover --mode sitemap` | 1 | Fast sitemap.xml parsing |
| Find pages + metadata | `discover --enriched` | 1 | lastmod/priority from sitemap |
| Monitor page for changes | `fetch --diff` | 1 | SHA256 content cache |

## Fallback Chain

```
fetch:  httpx+Trafilatura ─[empty/JS]─> Crawl4AI+Trafilatura ─[fail]─> error
scrape: httpx+BS4 ─[empty/JS]─> Crawl4AI+BS4 ─[fail]─> error
search: SearXNG ─[fail]─> Brave Search API ─[fail]─> [ddgs](https://github.com/deedy5/ddgs) (multi-engine) ─[fail]─> error
```

## Output Envelope

Every command returns JSON with `status` (`ok`|`partial`|`failed`), `command`, `timing_ms`, and `error` (on failure). Empty fields omitted.

- **fetch/crawl/extract**: `url`, `title`, `markdown`, `text`, `confidence`, `fetch_mode`, `extract_mode`; optional `char_count`, `truncated`, `chunk_index`, `chunk_count`, `chunk_tokens`, `changed`, `current_hash`, `previous_hash`. Always includes `citation` object (url, title, site_name, published_at, authors, citation_text) and source attribution appended to `markdown`.
- **scrape**: above + `tables` (3D array) or selector results or `--schema` JSON in `text`/`markdown`
- **search**: `query`, `results[]` (url, title, snippet, engine, engines[], score, domain, published_at, authors, quality_score, category, citation_index, meta_enriched[], meta_source), `total_results`, `number_of_results`, `citations[]`, `backend` ("searxng" | "brave" | "ddgs" — which provider was used)
- **discover**: `base_url`, `mode`, `urls[]`, `url_entries[]` (with depth/lastmod/priority), `total_urls`
- **fetch-batch**: NDJSON (one envelope per URL on stdout), each with `citation` object. Use `--json-array` for a single JSON array instead.
- **doctor**: `ready_commands[]`, `search_backend`, `checks[]` with status/hint per dependency

Full schema: `references/output-schema.md`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG instance URL |
| `SEARXNG_API_KEY` | (none) | Optional SearXNG API key |
| `CRAWL4AI_DOCKER_URL` | `http://localhost:11235` | Crawl4AI Docker server URL |
| `HTTP_TIMEOUT` | `30` | Default HTTP timeout (seconds) |
| `MAX_CONCURRENT_FETCHES` | `5` | Enforced by `fetch-batch` only |
| `BRAVE_API_KEY` | (none) | Optional: Brave Search API key (keyed fallback before ddgs) |

## References

Extended docs in `references/` — read on demand, not preloaded:

- `references/output-schema.md` — Full JSON schema with field descriptions
- `references/routing-guide.md` — Detailed routing decision tree and tradeoffs
- `references/advanced-patterns.md` — Multi-step research workflows
- `references/performance-table.md` — Benchmarks and tuning guide
- `references/searxng-setup.md` — SearXNG installation and configuration
- `examples/example-workflows.md` — Common workflow patterns
