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
  - Bash(*/web-intel:*)
  - Read
  - Write
  - Grep
  - Glob
metadata:
  requires:
    bins:
      - python3
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

> **Rate-limit all requests.** Max 5 concurrent fetches per domain.

> **JSON output only.** All commands emit JSON to stdout, logs to stderr.

## Path Resolution

All commands use the wrapper script or resolve the skill directory:

```bash
# Preferred: wrapper script (works from any CWD)
$SKILL_DIR/bin/web-intel <command> [OPTIONS]

# Alternative: direct python call
python3 $SKILL_DIR/scripts/web.py <command> [OPTIONS]
```

`$SKILL_DIR` is the skill's install directory (e.g., `~/.config/opencode/skills/web-intel`).

## Plug-and-Play Setup

**Tier 1 — Zero setup (works immediately):** `fetch`, `extract`, `discover`, `scrape`
Python deps auto-install on first run. No Docker needed.

```bash
$SKILL_DIR/bin/web-intel fetch "https://example.com" --pretty
```

**Tier 2 — Needs SearXNG Docker:** `search`

```bash
$SKILL_DIR/bin/web-intel setup --pretty           # auto-starts SearXNG
$SKILL_DIR/bin/web-intel search "query" --pretty
```

**Tier 3 — Needs Crawl4AI browser:** `crawl`, `fetch` fallback

```bash
$SKILL_DIR/bin/web-intel setup --tier all --pretty # installs everything
$SKILL_DIR/bin/web-intel crawl "https://spa.example.com" --pretty
```

## Diagnostic Commands

```bash
$SKILL_DIR/bin/web-intel doctor --pretty   # check all deps and services
$SKILL_DIR/bin/web-intel setup --pretty    # auto-fix: install deps, start SearXNG, create .env
$SKILL_DIR/bin/web-intel setup --tier all  # full setup including Crawl4AI browser
```

`doctor` returns JSON with `ready_commands` listing which commands work right now.

## Commands

### `search` — Web search via SearXNG (requires Docker)

```bash
$SKILL_DIR/bin/web-intel search "query" [--engines google,brave] [--categories general] [--language en] [--time-range week] [--max-results 10]
```

### `fetch` — Fast static page fetch + extraction

```bash
$SKILL_DIR/bin/web-intel fetch URL [--include-tables] [--include-links] [--include-images] [--favor-precision|--favor-recall] [--output-format markdown] [--no-fallback-crawl] [--timeout 30]
```

httpx fetches, Trafilatura extracts. Falls back to Crawl4AI if content is empty/JS-required.

### `crawl` — Dynamic/JS page crawl (browser, requires Crawl4AI)

```bash
$SKILL_DIR/bin/web-intel crawl URL [--wait-for CSS_SELECTOR] [--execute-js CODE] [--screenshot] [--pdf] [--timeout 60] [--docker]
```

### `scrape` — Structured data extraction (CSS selectors)

```bash
$SKILL_DIR/bin/web-intel scrape URL --selector CSS [--attribute href] [--use-crawl4ai]
$SKILL_DIR/bin/web-intel scrape URL --table [--use-crawl4ai]
$SKILL_DIR/bin/web-intel scrape URL --list
```

### `extract` — Content extraction from local HTML (no network)

```bash
$SKILL_DIR/bin/web-intel extract --html-file PATH [--url URL] [--include-tables] [--output-format markdown]
echo "<html>..." | $SKILL_DIR/bin/web-intel extract --stdin
```

### `discover` — Site URL discovery

```bash
$SKILL_DIR/bin/web-intel discover URL [--mode sitemap|crawl|both] [--max-urls 100]
```

## Routing Guide

| Task | Command | Tier | Why |
|------|---------|------|-----|
| Research a topic | `search` | 2 | Aggregates search engines via SearXNG |
| Read article/blog/docs | `fetch` | 1 | Fast httpx + clean Trafilatura extraction |
| JS-heavy SPA / login page | `crawl` | 3 | Renders JavaScript via browser |
| Extract data table (static) | `scrape --table` | 1 | BS4 preserves table structure |
| Extract data table (JS page) | `scrape --table --use-crawl4ai` | 3 | Render first, then BS4 |
| Extract specific elements | `scrape --selector` | 1 | CSS targeting via BS4 |
| Process local HTML | `extract --html-file` | 1 | No network, Trafilatura only |
| Find all pages on a site | `discover --mode sitemap` | 1 | Fast sitemap.xml parsing |

## Fallback Chain

```
fetch: httpx+Trafilatura ─[empty/JS]─> Crawl4AI+Trafilatura ─[fail]─> error
scrape: httpx+BS4 ─[empty/JS]─> Crawl4AI+BS4 ─[fail]─> error
search: SearXNG ─[fail]─> error with setup hint
```

## Output Envelope

Every command returns JSON with `status` (`ok`|`partial`|`failed`), `command`, `timing_ms`, and `error` (on failure). Empty fields omitted.

- **fetch/crawl/extract**: `url`, `title`, `markdown`, `text`, `confidence`, `fetch_mode`, `extract_mode`
- **scrape**: above + `tables` (3D array) or selector results
- **search**: `query`, `results[]` (url, title, snippet, engine, score), `total_results`
- **discover**: `base_url`, `mode`, `urls[]`, `total_urls`
- **doctor**: `ready_commands[]`, `checks[]` with status/hint per dependency
- **setup**: `steps[]` with status per action taken

Full schema: `references/output-schema.md`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG instance URL |
| `SEARXNG_API_KEY` | (none) | Optional SearXNG API key |
| `CRAWL4AI_DOCKER_URL` | `http://localhost:11235` | Crawl4AI Docker server URL |
| `HTTP_TIMEOUT` | `30` | Default HTTP timeout (seconds) |
| `MAX_CONCURRENT_FETCHES` | `5` | Max parallel fetches per domain |

## References

Extended docs in `references/` — read on demand, not preloaded:

- `references/output-schema.md` — Full JSON schema with field descriptions
- `references/routing-guide.md` — Detailed routing decision tree and tradeoffs
- `references/advanced-patterns.md` — Multi-step research workflows
- `references/performance-table.md` — Benchmarks and tuning guide
- `references/searxng-setup.md` — SearXNG installation and configuration
- `examples/example-workflows.md` — Common workflow patterns
