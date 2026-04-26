# Routing Guide

Decision tree for choosing the right command and component.

## By Content Type

| Content Type | Best Command | Why |
|---|---|---|
| Static article / blog | `fetch` | httpx is fast, Trafilatura excels at article extraction |
| Documentation page | `fetch` | Clean text extraction from semantic HTML |
| SPA / React / Vue app | `crawl` | Requires JavaScript rendering |
| Page behind cookie banner | `crawl --execute-js "..."` | Browser can dismiss banners |
| Data table on static page | `scrape --table` | BS4 preserves table structure |
| Data table on JS page | `scrape --table --use-crawl4ai` | Render JS first, then BS4 |
| Specific page section | `scrape --selector ".class"` | CSS targeting via BS4 |
| Multiple fields in one pass | `scrape --schema '{"title":"h1","price":".price"}'` | Avoids N round-trips |
| Link list / nav menu | `scrape --selector "nav a" --attribute href` | Extract href attributes |
| Local HTML file | `extract --html-file` | No network, Trafilatura only |
| Piped HTML | `extract --stdin` | Process HTML from another tool |
| All pages on a site | `discover --mode sitemap` | Fast sitemap.xml parsing |
| Pages + freshness metadata | `discover --enriched` | Adds lastmod/priority from sitemap XML |
| Deep site exploration | `discover --mode crawl` | BFS link-following with per-URL depth |

## By Task

| Task | Pipeline |
|---|---|
| Research a topic | `search` → `fetch` each top result |
| Research + read in one shot | `search --fetch-top 3` | Fetches and embeds content in results |
| Monitor a news source | `discover --enriched` → filter by `lastmod` → `fetch` new URLs |
| Extract product data | `scrape --schema '{"name":"h1","price":".price"}'` |
| Read a JS-heavy dashboard | `crawl --wait-for ".data-loaded"` |
| Compare sources | `search` → `fetch` multiple → compare markdown outputs |
| Archive a webpage | `fetch --include-tables --include-links` |
| Fetch many URLs (parallel) | `fetch-batch --concurrency 5 --domain-delay 1.0` |
| Pipe discovered URLs into fetch | `discover ... \| jq -r '.urls[]' \| fetch-batch` |
| Read long document in parts | `fetch --chunk-tokens 1000` (iterate `--chunk-index`) |
| Focus on relevant section | `fetch --relevant-to "query" --relevant-top 10` |
| Detect page changes | `fetch --diff` (returns `changed`, `current_hash`) |
| Wait for dynamic content | `fetch --wait-for-text "Loaded"` (static pages only; use `crawl` for JS) |

## Fallback Behavior

### `fetch`
1. **httpx + Trafilatura** (fast path, ~200-500ms)
2. If empty/failed AND JavaScript detected → **Crawl4AI** (slow path, ~3-10s)
3. Both fail → error with diagnostic message

### `search`
1. **SearXNG** (self-hosted, multi-engine, fully ranked)
2. If SearXNG unavailable → **Brave Search API** (if `BRAVE_API_KEY` is set)
3. If Brave unavailable → **[ddgs](https://github.com/deedy5/ddgs)** (zero-config, fans out to 6+ engines)
4. All fail → error

`quality_score` is fully computed only with SearXNG (term overlap + engine count + raw score). With ddgs/Brave fallbacks, only term overlap is available.

Disable fallbacks with `--no-fallback` to force SearXNG-only.

## Content Length Management

| Goal | Flag | Notes |
|---|---|---|
| Hard token cap | `--max-tokens N` | Truncates; sets `truncated=true` in output |
| Paginated reading | `--chunk-tokens N` + `--chunk-index I` | `chunk_count` in response tells total pages |
| Focus on relevant parts | `--relevant-to "query"` | TF-IDF paragraph filter; use with `--relevant-top N` |

`--chunk-tokens` and `--max-tokens` are mutually exclusive; `--chunk-tokens` takes precedence.

## Performance vs Accuracy Tradeoffs

| Flag | Effect |
|---|---|
| `--favor-precision` | Less content, higher quality (fewer false positives) |
| `--favor-recall` | More content, may include boilerplate (fewer false negatives) |
| Neither (default) | Balanced extraction |
| `--include-tables` | Slower extraction but captures tabular data |
| `--include-links` | Adds hyperlinks to output (useful for citation tracking) |
| `--no-rerank` | Preserve SearXNG raw ordering instead of quality_score reranking |

## Parallelism Notes

`fetch-batch` is the only safe parallel path. Shell loops calling `fetch` individually:
- Are not rate-limited per domain
- Cannot enforce concurrency limits
- May trigger target server rate limiting

Use `--domain-delay 1.0` in `fetch-batch` to enforce a 1-second gap between requests to the same domain.
