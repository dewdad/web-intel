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
| Link list / nav menu | `scrape --selector "nav a" --attribute href` | Extract href attributes |
| Local HTML file | `extract --html-file` | No network, Trafilatura only |
| Piped HTML | `extract --stdin` | Process HTML from another tool |
| All pages on a site | `discover --mode sitemap` | Fast sitemap.xml parsing |
| Deep site exploration | `discover --mode crawl` | Follows links from homepage |

## By Task

| Task | Pipeline |
|---|---|
| Research a topic | `search` → `fetch` each top result |
| Monitor a news source | `discover --mode sitemap` → `fetch` new URLs |
| Extract product data | `scrape --selector` or `scrape --table` |
| Read a JS-heavy dashboard | `crawl --wait-for ".data-loaded"` |
| Compare sources | `search` → `fetch` multiple → compare markdown outputs |
| Archive a webpage | `fetch --include-tables --include-links --include-images` |

## Fallback Behavior

The `fetch` command has a built-in fallback chain:

1. **httpx + Trafilatura** (fast path, ~200-500ms)
2. If empty/failed AND error mentions JavaScript → **Crawl4AI** (slow path, ~3-10s)
3. If both fail → error with diagnostic message

Disable fallback with `--no-fallback-crawl` to force httpx-only.

## Performance vs Accuracy Tradeoffs

| Flag | Effect |
|---|---|
| `--favor-precision` | Less content, higher quality (fewer false positives) |
| `--favor-recall` | More content, may include boilerplate (fewer false negatives) |
| Neither (default) | Balanced extraction |
| `--include-tables` | Slower extraction but captures tabular data |
| `--include-links` | Adds hyperlinks to output (useful for citation tracking) |
