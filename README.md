# web-intel

Web search, crawling, scraping, and content extraction for AI agents — routed through a single CLI.

```bash
bin/web-intel search "how does RLHF work"
bin/web-intel fetch "https://arxiv.org/abs/2203.02155"
bin/web-intel scrape "https://example.com" --schema '{"title":"h1","price":".price"}'
bin/web-intel discover "https://docs.python.org" --enriched
```

All output is JSON on stdout. Logs go to stderr only. Every command works immediately — no config required.

---

## Install

```bash
skillshare install dewdad/web-intel --track && skillshare sync
```

Or clone directly:

```bash
git clone https://github.com/dewdad/web-intel.git
cd web-intel
bin/web-intel doctor --pretty   # checks deps, auto-installs on first run
```

Python 3.11–3.13 required. Python deps auto-install on first use per command (no manual pip install).

---

## Commands

| Command | What it does | Needs |
|---------|-------------|-------|
| `fetch` | Fast static page fetch + Trafilatura extraction | nothing |
| `fetch-batch` | Parallel batch fetch from stdin or file (NDJSON out) | nothing |
| `extract` | Extract from local HTML file or stdin | nothing |
| `scrape` | Structured extraction via CSS selectors, tables, lists, or schema | nothing |
| `discover` | Sitemap/BFS crawl to list all URLs on a site | nothing |
| `search` | Multi-engine web search | Docker (or ddgs/Brave fallback) |
| `crawl` | JS-rendered page fetch via headless browser | Crawl4AI |
| `doctor` | Health check — shows which commands are ready | nothing |
| `setup` | Auto-install deps, start SearXNG, write `.env` | nothing |

### Quick examples

```bash
# Search and read the top 3 results in one shot
bin/web-intel search "LLM context window scaling" --fetch-top 3 --pretty

# Fetch a long doc, return only the chunk about "tokenization"
bin/web-intel fetch "https://huggingface.co/docs/tokenizers/quicktour" \
  --relevant-to "tokenization algorithm" --pretty

# Extract multiple fields from a product page
bin/web-intel scrape "https://pypi.org/project/httpx/" \
  --schema '{"name":"h1","version":".release-number","summary":".package-description"}' --pretty

# Monitor a page for changes
bin/web-intel fetch "https://example.com/changelog" --diff --pretty

# Paginate a long article (chunk 0 of N)
bin/web-intel fetch "https://longread.example.com" --chunk-tokens 1000 --chunk-index 0 --pretty

# Batch fetch a list of URLs with per-domain rate limiting
cat urls.txt | bin/web-intel fetch-batch --concurrency 5 --domain-delay 1.0

# Discover all pages on a site, then batch-fetch them
bin/web-intel discover "https://docs.example.com" --mode sitemap \
  | jq -r '.urls[:50][]' \
  | bin/web-intel fetch-batch --concurrency 3
```

---

## Setup tiers

**Tier 1 — zero setup** (`fetch`, `fetch-batch`, `extract`, `scrape`, `discover`): Python deps auto-install on first run.

**Tier 2 — Docker** (`search`): SearXNG runs in Docker for multi-engine search. Falls back to [ddgs](https://github.com/deedy5/ddgs) (zero-config) or Brave Search API if Docker is unavailable.

```bash
bin/web-intel setup --pretty        # starts SearXNG, creates .env
bin/web-intel search "query" --pretty
```

**Tier 3 — browser** (`crawl`, JS-gated pages): Crawl4AI + Chromium (~270MB one-time download).

```bash
bin/web-intel setup --tier all --pretty
bin/web-intel crawl "https://spa.example.com" --wait-for ".loaded" --pretty
```

---

## Search fallback chain

```
SearXNG (self-hosted, multi-engine)
  └─ Brave Search API  (if BRAVE_API_KEY is set)
       └─ ddgs  (zero-config, fans out to 6+ engines)
```

`doctor` shows which backend is active:

```bash
bin/web-intel doctor --pretty | jq '.search_backend'
```

---

## Output

All commands emit a JSON envelope:

```json
{
  "status": "ok",
  "command": "fetch",
  "url": "https://example.com",
  "title": "Example Domain",
  "markdown": "# Example Domain\n\nThis domain is for use in...",
  "confidence": 0.92,
  "timing_ms": 312
}
```

`status` is always `ok`, `partial`, or `failed`. Empty fields are omitted.

See [`references/output-schema.md`](references/output-schema.md) for the full field reference.

---

## Content length controls

| Goal | Flag |
|------|------|
| Hard token cap | `--max-tokens N` |
| Paginated reading | `--chunk-tokens N` + `--chunk-index I` |
| Focus on relevant sections | `--relevant-to "query"` |

`--chunk-tokens` and `--max-tokens` are mutually exclusive; `--chunk-tokens` takes precedence.

---

## Environment variables

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG instance URL |
| `BRAVE_API_KEY` | — | Optional Brave Search API key |
| `HTTP_TIMEOUT` | `30` | Default HTTP timeout (seconds) |
| `MAX_CONCURRENT_FETCHES` | `5` | Enforced by `fetch-batch` only |

---

## Project layout

```
bin/web-intel                   # self-resolving wrapper (works from any CWD)
scripts/
  web.py                        # CLI entry point + all command handlers
  _normalize.py                 # output dataclasses (WebResult, SearchResult, DiscoverResult)
  _httpx_fetch.py               # httpx + retry fetch
  _trafilatura_extract.py       # Trafilatura extraction, sitemap discovery, BFS crawl
  _bs4_scrape.py                # BeautifulSoup selector / table / list / schema extraction
  _crawl4ai_crawl.py            # Crawl4AI browser crawl
  _searxng.py                   # SearXNG search + quality scoring + dedup
  _search_fallback.py           # Brave + ddgs fallback search
  _relevance.py                 # TF-IDF paragraph relevance filter
  _page_cache.py                # SHA256 content hash cache (--diff)
  _deps.py                      # per-command auto-dependency installer
  _config.py                    # shared config, HTTP client, logging
docker/
  docker-compose.yml            # full stack
  docker-compose.searxng.yml    # SearXNG only
  searxng/settings.yml          # SearXNG config (must include json in search.formats)
references/
  output-schema.md              # full JSON field reference
  routing-guide.md              # when to use which command
  advanced-patterns.md          # multi-step research workflows
  performance-table.md          # benchmarks and tuning
  searxng-setup.md              # SearXNG install and config
tests/                          # unit tests (pytest, no network required)
examples/example-workflows.md  # common workflow patterns
```

---

## Tests

```bash
python3 -m pytest tests/ -v
```

56 unit tests covering all pure-function modules. No network or Docker required.

The existing `tests/e2e_test.py` tests require live services (SearXNG, Crawl4AI) and are intentionally excluded from the default run.

---

## Routing quick reference

| Content type | Command |
|---|---|
| Static article / docs | `fetch` |
| JS-rendered SPA | `crawl` |
| Multiple fields from one page | `scrape --schema` |
| Data table | `scrape --table` |
| All URLs on a site | `discover` |
| Batch of URLs | `fetch-batch` |
| Web search | `search` |
| Search + read top results | `search --fetch-top N` |

Full decision tree: [`references/routing-guide.md`](references/routing-guide.md)

---

## License

MIT — see [LICENSE](LICENSE).
