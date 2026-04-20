# [AGENTS.md](http://AGENTS.md)
## What this is
`web-intel` — a Git repo (`dewdad/web-intel`) containing the `web-intel` skill. It provides AI agents with web search, crawling, scraping, and content extraction via a unified CLI (`scripts/web.py`).
Not a Python package — no `setup.py`, `pyproject.toml`, or build system. Install with [skillshare](https://github.com/runkids/skillshare):
```bash
skillshare install dewdad/web-intel --track && skillshare sync

```
## Plug-and-play architecture
The skill is designed to work immediately when copied into a skills folder. Three tiers:
- **Tier 1 (zero setup)**: `fetch`, `extract`, `discover`, `scrape` — Python deps auto-install on first run

- **Tier 2 (needs Docker)**: `search` — requires SearXNG container, auto-started via `setup`

- **Tier 3 (needs browser)**: `crawl` — requires Crawl4AI browser, installed via `setup --tier all`

Path resolution: `bin/web-intel` is a self-resolving wrapper script. It finds its own location, picks a compatible Python (3.11-3.13 preferred over 3.14+), and calls `scripts/web.py`. Works from any CWD.
## Commands
```bash
bin/web-intel {search,fetch,crawl,scrape,extract,discover,doctor,setup} [OPTIONS]

```
All output is JSON on stdout. Logs go to stderr only. **Never print non-JSON to stdout** — downstream consumers parse it.
- `doctor` — checks all deps, services, Python version; reports `ready_commands[]`

- `setup [--tier core|all]` — auto-installs deps, creates `.env`, starts SearXNG

## Architecture (what isn't obvious from filenames)
- `web.py` inserts `scripts/` into `sys.path`. All `_*.py` sibling imports resolve at runtime, not via packages. **Pyright will flag these as **`reportMissingImports`** — ignore them.**

- External library imports (`httpx`, `trafilatura`, `bs4`, `crawl4ai`) also show as Pyright errors because they're runtime deps, not dev deps. Expected.

- `_deps.py` auto-installs missing pip packages per command on first run. A stamp file in `.deps_cache/` prevents re-checking on subsequent runs. On Python 3.14+, it auto-detects and uses an older Python for pip installs if available.

- Command handlers in `web.py` use **lazy imports** (inside function bodies) so `_deps.ensure_deps()` runs before any external library is loaded.

- `doctor` and `setup` subcommands bypass `ensure_deps` — they manage deps themselves.

## Dependency tiers
| Commands | Packages needed |
| --- | --- |
| `extract`, `discover` | trafilatura |
| `search`, `scrape`, `fetch` | httpx, httpx-retries, trafilatura, beautifulsoup4, lxml |
| `crawl` | all above + crawl4ai |

`fetch` uses crawl4ai as an optional fallback only — it is not a hard dependency.
`_deps._COMMAND_DEPS` is the source of truth. Keep it in sync with actual imports in each module.
## External services
- **SearXNG** (Docker): Required for `search` command. Auto-started by `setup`. Config at `docker/searxng/settings.yml` must have `json` in `search.formats` or the API returns HTML.

- **Crawl4AI browser**: `crawl` and `fetch` (fallback) use Chromium via Playwright. Run `crawl4ai-setup` once (or `setup --tier all`) to install the browser (~270MB).

- **Crawl4AI Docker server** (optional): For `--docker` flag. Port 11235.

## Output contract
Every command returns a JSON envelope via `_normalize.emit()`. Envelope types:
- `WebResult` — fetch, crawl, scrape, extract

- `SearchResult` — search

- `DiscoverResult` — discover

- Dict envelopes — doctor, setup

The `status` field is always present: `ok`, `partial`, or `failed`. On failure, `error` contains a diagnostic string.
## Files to never edit blindly
- `_deps._IMPORT_MAP` — maps pip package names to Python import names (e.g., `beautifulsoup4` → `bs4`). Wrong mapping = silent dep-check failure.

- `_deps._COMMAND_DEPS` — must match actual imports in each command handler. Mismatch = runtime ImportError after stamp says deps are OK.

- `docker/searxng/settings.yml` `search.formats` — must include `json`. Removing it silently breaks the search command.

## File structure
```
web-intel/
├── SKILL.md              # Skill definition (agent-facing, lean)
├── AGENTS.md             # Developer context (this file)
├── .env.example          # Environment variable template
├── bin/
│   └── web-intel         # Self-resolving wrapper script (works from any CWD)
├── scripts/
│   ├── web.py            # CLI entry point + router + doctor/setup
│   ├── _deps.py          # Auto-dependency installer with stamp cache
│   ├── _config.py        # Shared config, httpx client factory, logging
│   ├── _normalize.py     # Output normalization + JSON envelope
│   ├── _searxng.py       # SearXNG search module
│   ├── _httpx_fetch.py   # httpx + RetryTransport fetch
│   ├── _trafilatura_extract.py  # Trafilatura extraction + discovery
│   ├── _bs4_scrape.py    # BeautifulSoup structured extraction
│   └── _crawl4ai_crawl.py      # Crawl4AI browser crawling
├── references/           # Extended docs (not injected into agent context)
│   ├── output-schema.md  # Full JSON output schema
│   ├── routing-guide.md  # Detailed routing decision tree
│   ├── advanced-patterns.md  # Multi-step research workflows
│   ├── performance-table.md  # Benchmarks and tuning
│   └── searxng-setup.md  # SearXNG install and config
├── examples/
│   └── example-workflows.md
└── docker/
    ├── docker-compose.yml           # Full stack
    ├── docker-compose.searxng.yml   # SearXNG only
    └── searxng/settings.yml         # SearXNG config

```
## Dependency auto-install
`_deps.py` handles automatic installation per command. The flow:
- `ensure_deps(command)` is called before any handler runs

- Checks `.deps_cache/{hash}.stamp` — if fresh, skips entirely

- If Python ≥ 3.14, warns and tries to use an older Python for pip installs

- If missing/stale, verifies each package can be imported (via `_IMPORT_MAP`)

- Installs missing packages with `pip install --quiet --upgrade`

- Writes stamp file on success

To force re-check: `rm -rf .deps_cache/`
## Conventions
- No tests exist. Verify changes by running: `bin/web-intel doctor --pretty` for full health check, or `bin/web-intel  --help` for parse check, actual URLs for integration check.

- `--pretty` flag on every subcommand for human-readable JSON output.

- Config comes from `.env` file (loaded by `_config._load_dotenv()`). Env vars override `.env` values. See `.env.example` for all options.

- `self_updating: true` in [SKILL.md](http://SKILL.md) frontmatter — skill may evolve rapidly.