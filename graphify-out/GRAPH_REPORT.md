# Graph Report - .  (2026-04-26)

## Corpus Check
- Corpus is ~9,849 words - fits in a single context window. You may not need a graph.

## Summary
- 195 nodes · 365 edges · 16 communities detected
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 101 edges (avg confidence: 0.74)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_E2E Test Suite|E2E Test Suite]]
- [[_COMMUNITY_BS4 Scrape Module|BS4 Scrape Module]]
- [[_COMMUNITY_Output Normalization|Output Normalization]]
- [[_COMMUNITY_HTTP Client Config|HTTP Client Config]]
- [[_COMMUNITY_Dependency Management|Dependency Management]]
- [[_COMMUNITY_Fetch & Fallback Chain|Fetch & Fallback Chain]]
- [[_COMMUNITY_Dep Auto-Install|Dep Auto-Install]]
- [[_COMMUNITY_CLI Entry & Env Config|CLI Entry & Env Config]]
- [[_COMMUNITY_SearXNG Search|SearXNG Search]]
- [[_COMMUNITY_Text Extraction & Discovery|Text Extraction & Discovery]]
- [[_COMMUNITY_Crawl4AI Browser Crawl|Crawl4AI Browser Crawl]]
- [[_COMMUNITY_Output Schema Contracts|Output Schema Contracts]]
- [[_COMMUNITY_Scrape Command|Scrape Command]]
- [[_COMMUNITY_Skill & Agent Docs|Skill & Agent Docs]]
- [[_COMMUNITY_JSON-Only Stdout Contract|JSON-Only Stdout Contract]]
- [[_COMMUNITY_Docker Full Stack|Docker Full Stack]]

## God Nodes (most connected - your core abstractions)
1. `_run()` - 29 edges
2. `Timer` - 28 edges
3. `WebResult` - 21 edges
4. `fetch Command` - 13 edges
5. `emit()` - 11 edges
6. `cmd_scrape()` - 10 edges
7. `TestFetch` - 9 edges
8. `web.py — CLI Entry Point & Router` - 9 edges
9. `SearXNG — Federated Search Engine` - 9 edges
10. `DiscoverResult` - 7 edges

## Surprising Connections (you probably didn't know these)
- `_config.py — Shared Config & httpx Client Factory` --references--> `SEARXNG_URL Environment Variable`  [INFERRED]
  AGENTS.md → SKILL.md
- `_config.py — Shared Config & httpx Client Factory` --references--> `HTTP_TIMEOUT Environment Variable`  [INFERRED]
  AGENTS.md → SKILL.md
- `_config.py — Shared Config & httpx Client Factory` --references--> `MAX_CONCURRENT_FETCHES Environment Variable`  [INFERRED]
  AGENTS.md → SKILL.md
- `Check all dependencies and services. Emits JSON diagnostic.` --uses--> `Timer`  [INFERRED]
  /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py → /Users/i071496/copilot-projects/web-intel-skill/scripts/_normalize.py
- `Auto-setup: install deps, start SearXNG, configure .env.` --uses--> `Timer`  [INFERRED]
  /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py → /Users/i071496/copilot-projects/web-intel-skill/scripts/_normalize.py

## Hyperedges (group relationships)
- **Tier 1 Zero-Setup Commands** — cmd_fetch, cmd_extract, cmd_discover, cmd_scrape [EXTRACTED 1.00]
- **Tier 2 Docker-Required Commands** — cmd_search [EXTRACTED 1.00]
- **Tier 3 Browser-Required Commands** — cmd_crawl [EXTRACTED 1.00]
- **Core Script Modules in scripts/** — script_web_py, script_deps_py, script_config_py, script_normalize_py, script_searxng_py, script_httpx_fetch_py, script_trafilatura_extract_py, script_bs4_scrape_py, script_crawl4ai_crawl_py [EXTRACTED 1.00]
- **Fetch Pipeline: httpx + Trafilatura with Crawl4AI fallback** — cmd_fetch, lib_httpx, lib_trafilatura, lib_crawl4ai, concept_fallback_chain [EXTRACTED 1.00]
- **Search Pipeline: SearXNG + Docker** — cmd_search, lib_searxng, docker_compose_searxng, docker_searxng_settings [EXTRACTED 1.00]
- **JSON Output Contract across all commands** — concept_json_only_stdout, output_web_result, output_search_result, output_discover_result, script_normalize_py [EXTRACTED 1.00]
- **Dependency Auto-Install System** — script_deps_py, concept_ensure_deps, concept_import_map, concept_command_deps, deps_cache [EXTRACTED 1.00]
- **Research Workflow Pattern: search → fetch** — workflow_research_pipeline, cmd_search, cmd_fetch [EXTRACTED 1.00]

## Communities

### Community 0 - "E2E Test Suite"
Cohesion: 0.07
Nodes (12): End-to-end tests for the web-intel skill CLI.  Run with:     python -m pytest te, _run(), _searxng_available(), _searxng_url(), TestCrawlDocker, TestDiscover, TestDoctor, TestExtract (+4 more)

### Community 1 - "BS4 Scrape Module"
Cohesion: 0.11
Nodes (30): Extract all ordered and unordered lists from HTML., Extract elements matching a CSS selector from HTML., Extract all HTML tables as structured JSON arrays., scrape_lists(), scrape_selector(), scrape_tables(), crawl(), _crawl_docker() (+22 more)

### Community 2 - "Output Normalization"
Cohesion: 0.18
Nodes (19): emit(), emit_error(), Unified output envelope for all web-intel commands., Write JSON to stdout. All output goes through this single function., Emit a standardized error envelope., build_parser(), cmd_crawl(), cmd_discover() (+11 more)

### Community 3 - "HTTP Client Config"
Cohesion: 0.13
Nodes (12): create_async_httpx_client(), create_httpx_client(), get_logger(), _load_dotenv(), Shared configuration, httpx client factory, and logging for web-intel., Create a configured httpx.AsyncClient with retry transport.      Caller is respo, Load .env file into os.environ. No-op if file missing., Return a logger that writes to stderr only. (+4 more)

### Community 4 - "Dependency Management"
Cohesion: 0.17
Nodes (13): doctor Command, _deps._COMMAND_DEPS — Source of Truth for Command Dependencies, Dependency Tiers Architecture, ensure_deps() — Per-Command Dependency Check, _deps._IMPORT_MAP — pip-to-import Name Mapping, Lazy Imports Pattern — ensure_deps before library load, .deps_cache/ — Dependency Stamp Cache, Rationale: _IMPORT_MAP maps pip names to Python import names to detect installed packages (+5 more)

### Community 5 - "Fetch & Fallback Chain"
Cohesion: 0.25
Nodes (11): fetch Command, Fallback Chain — httpx → Crawl4AI → error, Precision vs Recall Extraction Tuning, httpx — HTTP Client Library, httpx-retries — Retry Transport for httpx, Rationale: httpx fast path with Crawl4AI fallback for JS pages, references/advanced-patterns.md — Multi-Step Workflows, references/routing-guide.md — Routing Decision Tree (+3 more)

### Community 6 - "Dep Auto-Install"
Cohesion: 0.42
Nodes (7): ensure_deps(), _find_compatible_python(), _import_name(), _is_importable(), _missing(), _pip_install(), _stamp_path()

### Community 7 - "CLI Entry & Env Config"
Cohesion: 0.29
Nodes (7): bin/web-intel — Self-Resolving Wrapper Script, .env — Environment Configuration File, HTTP_TIMEOUT Environment Variable, MAX_CONCURRENT_FETCHES Environment Variable, SEARXNG_URL Environment Variable, _config.py — Shared Config & httpx Client Factory, web.py — CLI Entry Point & Router

### Community 8 - "SearXNG Search"
Cohesion: 0.52
Nodes (7): search Command, docker-compose.searxng.yml — SearXNG Only Stack, docker/searxng/settings.yml — SearXNG Config, SearXNG — Federated Search Engine, references/searxng-setup.md — SearXNG Install & Config, _searxng.py — SearXNG Search Module, SearXNG search.formats JSON Requirement

### Community 9 - "Text Extraction & Discovery"
Cohesion: 0.6
Nodes (6): discover Command, extract Command, examples/example-workflows.md — Common Workflow Patterns, Trafilatura — Content Extraction Library, _trafilatura_extract.py — Trafilatura Extraction & Discovery, Tier 1 — Zero Setup Commands

### Community 10 - "Crawl4AI Browser Crawl"
Cohesion: 0.4
Nodes (6): crawl Command, setup Command, CRAWL4AI_DOCKER_URL Environment Variable, Crawl4AI — Browser-Based Crawling Library, _crawl4ai_crawl.py — Crawl4AI Browser Crawling, JS-Heavy Site Workflow

### Community 11 - "Output Schema Contracts"
Cohesion: 0.6
Nodes (5): DiscoverResult — JSON Envelope (discover), SearchResult — JSON Envelope (search), WebResult — JSON Envelope (fetch/crawl/scrape/extract), references/output-schema.md — Full JSON Schema, _normalize.py — Output Normalization & JSON Envelope

### Community 12 - "Scrape Command"
Cohesion: 0.67
Nodes (4): scrape Command, BeautifulSoup4 — HTML Parsing Library, lxml — XML/HTML Parser, _bs4_scrape.py — BeautifulSoup Structured Extraction

### Community 13 - "Skill & Agent Docs"
Cohesion: 0.67
Nodes (3): web-intel Developer Context (AGENTS.md), references/performance-table.md — Benchmarks & Tuning, web-intel Skill

### Community 14 - "JSON-Only Stdout Contract"
Cohesion: 1.0
Nodes (2): JSON-Only stdout Contract, Rationale: JSON-only stdout for downstream consumers

### Community 15 - "Docker Full Stack"
Cohesion: 1.0
Nodes (1): docker-compose.yml — Full Stack

## Knowledge Gaps
- **27 isolated node(s):** `End-to-end tests for the web-intel skill CLI.  Run with:     python -m pytest te`, `Unified output envelope for all web-intel commands.`, `Single-page result envelope.`, `Search results envelope.`, `Site discovery envelope.` (+22 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `JSON-Only Stdout Contract`** (2 nodes): `JSON-Only stdout Contract`, `Rationale: JSON-only stdout for downstream consumers`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Docker Full Stack`** (1 nodes): `docker-compose.yml — Full Stack`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Timer` connect `BS4 Scrape Module` to `Output Normalization`, `HTTP Client Config`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `create_httpx_client()` connect `HTTP Client Config` to `BS4 Scrape Module`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `Timer` (e.g. with `Check all dependencies and services. Emits JSON diagnostic.` and `Auto-setup: install deps, start SearXNG, configure .env.`) actually correct?**
  _`Timer` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `WebResult` (e.g. with `Fetch URL content via httpx. Returns (html_body, status_code, response_headers).` and `Fetch URL and return a WebResult with raw HTML in the text field.`) actually correct?**
  _`WebResult` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `fetch Command` (e.g. with `_httpx_fetch.py — httpx + RetryTransport Fetch` and `HTTP_TIMEOUT Environment Variable`) actually correct?**
  _`fetch Command` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `emit()` (e.g. with `cmd_search()` and `cmd_fetch()`) actually correct?**
  _`emit()` has 8 INFERRED edges - model-reasoned connections that need verification._
- **What connects `End-to-end tests for the web-intel skill CLI.  Run with:     python -m pytest te`, `Unified output envelope for all web-intel commands.`, `Single-page result envelope.` to the rest of the system?**
  _27 weakly-connected nodes found - possible documentation gaps or missing edges._