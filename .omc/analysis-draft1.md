---

## Review: `web-intel` Skill

I read every source file. Here's an honest, thorough assessment.

---

### What it is (accurately)

A **self-contained CLI** that gives agents a single unified interface for web work across 6 functional tiers: keyword search (SearXNG), static fetch+extraction (httpx+Trafilatura), structured scraping (BS4), JS rendering (Crawl4AI), local HTML processing, and URL discovery. The philosophy is: one tool, consistent JSON envelopes, escalating setup cost.

---

### What's genuinely strong

**1. The tiered zero-to-full-power UX is the right idea**
Tier 1 works immediately with zero setup. Tier 2 adds Docker. Tier 3 adds a browser. Most agent tasks only need Tier 1. This is a thoughtful onboarding ramp — far better than forcing Docker as a prerequisite.

**2. Envelope discipline is excellent**
Every command returns the same `status/command/timing_ms/error` skeleton. `WebResult` is rich and consistent. Empty fields are stripped. This is exactly right for agent consumption — predictable, parseable, minimal.

**3. Lazy imports + stamp-based dep caching**
The `_deps.py` approach — lazy per-command import, MD5-stamped install cache, Python 3.14+ fallback — is genuinely clever for a CLI that doesn't own its environment. No startup cost unless you need it.

**4. `doctor` + `setup` are first-class**
Self-diagnosing tools that emit JSON with `ready_commands[]` and per-check hints is a killer UX for agents. An agent can run `doctor` first and know exactly what's available before trying to use it. This is rare and valuable.

**5. The fallback chain (`fetch → Crawl4AI`) is the right architecture**
Try cheap path first, fall back to expensive path only on signals. The `_FETCH_FALLBACK_SIGNALS` heuristic is pragmatic and the `--no-fallback-crawl` escape hatch is thoughtful.

**6. `extract --stdin` / pipe support**
Being able to pipe raw HTML in is excellent for composability — agents can get HTML from anywhere and process it.

---

### Real gaps and weaknesses

**1. `search` depends on a running Docker container — and has no fallback**
This is the biggest usability cliff. `fetch` degrades gracefully; `search` just returns `failed`. For an agent that can't run Docker (CI, sandboxed environments, corporate laptops), `search` is dead. The skill could fall back to a public API (DuckDuckGo instant answers, Brave Search API, or even a scraper of a search SERP) when SearXNG isn't available. Even a `--no-docker` flag that tries a best-effort alternative would help enormously.

**2. The search result is too shallow**
`_searxng.py` returns `url, title, snippet, engine, score`. There's no `published_date`, no `categories`, no `domain`, no deduplication by domain. Agents doing research get a flat list with no signal to prioritize. Compare to Exa/Tavily which return semantic relevance scores, highlights, and publication dates by default.

**3. `scrape` has no multi-selector support**
You get one `--selector` per invocation. Extracting structured data from a page often requires pulling from 2–4 different selectors in one pass (e.g., title + price + rating). Right now agents need multiple round-trips per URL.

**4. `discover` gives you URLs but no metadata**
`discover` returns a flat `urls[]` list. There's no title, no last-modified, no priority (from sitemap), no depth. For agents building knowledge bases from a site, you'd immediately want to batch-fetch and rank — but there's no signal to do that without a full round-trip to every URL.

**5. No content chunking / token-budget awareness**
The `markdown` field can be enormous for a long page. Agents operating under token budgets have no way to request "first N characters", "summary only", or "most relevant section to query X". Trafilatura doesn't do this, but a post-processing layer could. This is probably the #1 practical pain point when feeding results into LLMs.

**6. `_trafilatura_extract.py` calls `trafilatura.extract()` twice**
Once for `output_format="txt"` and once for `output_format="markdown"`, then a third call for metadata (`xmltei`). That's 3 extraction passes on the same HTML. It's a correctness smell (slight divergence in results) and a performance issue (~3x the extraction cost). The markdown output should be the primary path; `text` could be derived from it.

**7. `get_raw_html` in `_crawl4ai_crawl.py` is lossy**
`get_raw_html()` returns `result.text or result.markdown` — but Crawl4AI's `text` field is extracted content, not raw HTML. Feeding extracted markdown into BS4's table parser won't work correctly. This is a latent bug: `scrape --table --use-crawl4ai` on some pages will silently fail to find tables because BS4 gets markdown instead of HTML.

**8. No rate-limiting enforcement in the code**
`MAX_CONCURRENT_FETCHES=5` is defined but nothing in the CLI actually enforces it for parallel calls. The note in SKILL.md says "max 5 concurrent fetches per domain" but it's aspirational — the code is single-threaded per invocation. Agents running batches via shell loops have no guard.

**9. No tests beyond e2e_test.py (which requires live services)**
The single `e2e_test.py` presumably requires SearXNG + live internet. There are no unit tests for the parsing modules, envelope normalization, or dep-check logic. `_bs4_scrape.py`, `_normalize.py`, and `_deps.py` could all be tested in isolation.

---

### What could be the killer features

These are the features that would make this genuinely exceptional rather than merely good:

**🔥 1. `fetch --relevant-to "query"`  — semantic section extraction**
Instead of dumping the full markdown, extract the N paragraphs most relevant to a given query. This solves the token-budget problem and is the single most valuable thing for research agents. Could be implemented post-extraction with a simple TF-IDF or embedding similarity over paragraphs — no LLM needed.

**🔥 2. `search --fetch-top N` — one-shot search-and-read pipeline**
`search "query" --fetch-top 3` runs search, fetches the top 3 results in parallel, and returns a combined envelope with `results[].content` populated. This is what 80% of agent research tasks actually need. Right now it requires shell scripting with `jq` and loops. Collapsing it into one command is a force multiplier.

**🔥 3. Search fallback chain mirroring fetch's fallback**
`SearXNG → DuckDuckGo HTML scrape → Brave Search API (if key set)`. Agents shouldn't have to know about Docker availability. The skill should transparently degrade. `doctor` already reports `ready_commands` — the skill just needs to honour it at runtime.

**🔥 4. `--max-tokens N` / `--chunk-size N` on fetch/crawl/extract**
Emit content in token-budget-aware chunks, or truncate to N tokens with a `truncated: true` flag. The envelope already has `timing_ms` and `confidence` — adding `char_count` and `truncated` would be trivial and enormously useful.

**⭐ 5. `fetch --diff URL` — change detection**
Fetch a URL and compare to a cached version (stored in `.deps_cache/` or a simple local file). Return a diff/change summary. Monitors, news bots, and documentation tracking agents would love this.

**⭐ 6. `scrape --schema JSON` — structured extraction with a schema**
Pass a JSON schema describing what you want (e.g., `{"title": "h1", "price": ".price-tag", "rating": ".star-rating"}`) and get back a structured object. One command, one round-trip, typed output. This is Firecrawl's core value proposition and it could be done in pure BS4.

**⭐ 7. Metadata-enriched discover**
Return `{url, title, last_modified, priority, depth}` per URL from sitemap/crawl. Agents can then rank or filter before fetching rather than doing N blind round-trips.

**⭐ 8. `fetch --wait-for-text "phrase"` on static pages**
Trafilatura sometimes gets partial content on pages that stream content or have lazy-load patterns. A simple retry-until-text-present loop (with timeout) would bridge the gap between static and dynamic without needing the full browser.

---

### Architecture suggestions

| Issue | Fix |
|---|---|
| Triple extraction pass in `_trafilatura_extract.py` | Extract once to markdown, derive text via `re.sub` on markdown syntax |
| `get_raw_html` returning markdown instead of HTML | Store `result.html` from Crawl4AI (it returns `html` field) and use that |
| No parallel fetch support | Add `fetch-batch` command that accepts a newline-delimited URL list from stdin and runs `asyncio.gather` |
| Confidence is hardcoded (0.85, 0.9, 0.95) | Compute it: `len(extracted) / len(html)` gives a reasonable content density signal |

---

### Summary judgment

**Tier: solid B+, close to A- with targeted work.**

The bones are right. The architecture is clean, the envelope discipline is real, the tiered UX is thoughtful, and `doctor`/`setup` show genuine craft. The gaps are almost all in the "power user / agent efficiency" layer: shallow search results, no token-budget control, no one-shot search+fetch, and the `get_raw_html` bug. Fix those five things and this becomes a genuinely excellent agent research primitive.

The **real killer feature gap** is one-shot `search --fetch-top N`. That single addition would make the workflow in 90% of research agent tasks collapse from 10+ shell commands to 1. It's the Firecrawl/Exa killer feature and it's entirely implementable within the existing architecture.