---
name: web-intel
description: >
  Web search, crawling, scraping, and content extraction for AI agents.
  Routes tasks to SearXNG, httpx, Trafilatura, BeautifulSoup, or Crawl4AI
  based on content type and page complexity.
version: 0.1.0
self_updating: true
allowed-tools:
  - Bash(python3:*)
  - Bash(python:*)
  - Bash(docker:*)
  - Bash(docker-compose:*)
  - Bash(curl:*)
  - Read
  - Write
  - Grep
  - Glob
metadata:
  requires:
    bins:
      - python3
      - docker
    python:
      - httpx[http2]
      - httpx-retries
      - trafilatura
      - beautifulsoup4
      - lxml
      - crawl4ai
    skills: []
  tags:
    - web
    - search
    - scraping
    - crawling
    - research
---

# Web Intel

> **Rate-limit all requests.** Max 5 concurrent fetches per domain. SearXNG has built-in limiting — don't bypass it.

> **Respect robots.txt.** Trafilatura and Crawl4AI handle this. For raw httpx, check robots.txt first.

> **JSON output only.** All commands emit JSON to stdout, logs to stderr. Never mix.

> **Secrets in `.env` only.** Never hardcode credentials. The `.env` file is gitignored.

## Quick Start

```bash
docker compose -f docker/docker-compose.searxng.yml up -d   # SearXNG for search
cp .env.example .env                                         # configure
python3 scripts/web.py search "query"                        # run (deps auto-install)
```

## Commands

All commands: `python3 scripts/web.py {command} [OPTIONS]`. Use `--pretty` for formatted output.

### `search` — Web search via SearXNG

```bash
python3 scripts/web.py search "query" [--engines google,brave] [--categories general] [--language en] [--time-range week] [--max-results 10] [--pageno 1]
```

### `fetch` — Fast static page fetch + extraction

```bash
python3 scripts/web.py fetch URL [--include-tables] [--include-links] [--include-images] [--favor-precision|--favor-recall] [--output-format markdown] [--no-fallback-crawl] [--timeout 30]
```

httpx fetches, Trafilatura extracts. Falls back to Crawl4AI if content is empty/JS-required.

### `crawl` — Dynamic/JS page crawl (browser)

```bash
python3 scripts/web.py crawl URL [--wait-for CSS_SELECTOR] [--execute-js CODE] [--screenshot] [--pdf] [--timeout 60] [--no-headless] [--docker]
```

Use for SPAs, JS-heavy pages, pages behind cookie banners.

### `scrape` — Structured data extraction (CSS selectors)

```bash
python3 scripts/web.py scrape URL --selector CSS [--attribute href] [--use-crawl4ai]
python3 scripts/web.py scrape URL --table [--use-crawl4ai]
python3 scripts/web.py scrape URL --list [--use-crawl4ai]
```

### `extract` — Content extraction from local HTML (no network)

```bash
python3 scripts/web.py extract --html-file PATH [--url URL] [--include-tables] [--include-links] [--output-format markdown]
echo "<html>..." | python3 scripts/web.py extract --stdin
```

### `discover` — Site URL discovery

```bash
python3 scripts/web.py discover URL [--mode sitemap|crawl|both] [--max-urls 100] [--language en]
```

## Routing Guide

| Task | Command | Why |
|------|---------|-----|
| Research a topic | `search` | Aggregates multiple engines via SearXNG |
| Read article/blog/docs | `fetch` | Fast httpx + clean Trafilatura extraction |
| JS-heavy SPA / login page | `crawl` | Renders JavaScript via Crawl4AI browser |
| Extract data table (static) | `scrape --table` | BS4 preserves table structure |
| Extract data table (JS page) | `scrape --table --use-crawl4ai` | Render first, then BS4 |
| Extract specific elements | `scrape --selector ".class"` | CSS targeting via BS4 |
| Process local HTML | `extract --html-file` | No network, Trafilatura only |
| Find all pages on a site | `discover --mode sitemap` | Fast sitemap.xml parsing |
| Deep site exploration | `discover --mode crawl` | Follows links from homepage |

## Fallback Chain

```
fetch: httpx+Trafilatura ─[empty/JS]─> Crawl4AI+Trafilatura ─[fail]─> error
crawl: Crawl4AI ─[fail]─> error with diagnostic
scrape: httpx+BS4 ─[empty/JS]─> Crawl4AI+BS4 ─[fail]─> error
search: SearXNG ─[fail]─> error with setup hint
```

## Output Envelope

Every command returns JSON with `status` (`ok`|`partial`|`failed`), `command`, `timing_ms`, and `error` (on failure). Empty fields omitted.

- **fetch/crawl/extract**: `url`, `title`, `markdown`, `text`, `confidence`, `fetch_mode`, `extract_mode`
- **scrape**: above + `tables` (3D array) or selector results
- **search**: `query`, `results[]` (url, title, snippet, engine, score), `total_results`
- **discover**: `base_url`, `mode`, `urls[]`, `total_urls`

Full schema: `references/output-schema.md`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG instance URL |
| `SEARXNG_API_KEY` | (none) | Optional SearXNG API key |
| `CRAWL4AI_DOCKER_URL` | `http://localhost:11235` | Crawl4AI Docker server URL |
| `CRAWL4AI_API_KEY` | (none) | Optional Crawl4AI API key |
| `HTTP_TIMEOUT` | `30` | Default HTTP timeout (seconds) |
| `MAX_CONCURRENT_FETCHES` | `5` | Max parallel fetches per domain |
| `USER_AGENT` | (auto) | Custom User-Agent string |

## References

Extended docs in `references/` — read on demand, not preloaded:

- `references/output-schema.md` — Full JSON schema with field descriptions
- `references/routing-guide.md` — Detailed routing decision tree and tradeoffs
- `references/advanced-patterns.md` — Multi-step research workflows
- `references/performance-table.md` — Benchmarks and tuning guide
- `references/searxng-setup.md` — SearXNG installation and configuration
- `examples/example-workflows.md` — Common workflow patterns
