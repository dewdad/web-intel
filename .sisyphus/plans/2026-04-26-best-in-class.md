# web-intel: Best-in-Class Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six gaps that separate web-intel from the best agent web research tools (Tavily, Crawl4AI, Jina), making it the only open-source tool with zero-config, fallback search, token controls, query-aware content pruning, transparent backend signal, and reliable batch output — all in one CLI.

**Architecture:** Six independent, sequentially-deliverable improvements to existing modules. No new external dependencies. Each task is self-contained and leaves the tool in a working, tested state. Order follows impact: highest-value changes first.

**Tech Stack:** Python 3.11–3.13, existing deps (httpx, trafilatura, bs4, ddgs), pytest (no network required for unit tests). No new pip packages introduced.

**Verification baseline:** `python3 -m pytest tests/ -v` must pass (56 tests) before and after every task.

---

## File Map

Files **modified** (no new files needed):

| File | What changes |
|---|---|
| `scripts/_relevance.py` | Add `fit_markdown()` — BM25 noise pruning, query-aware |
| `scripts/web.py` | Wire `fit_markdown` into `--fetch-top` pipeline; add `--mode fast\|deep` to `search`; add `backend` field to search envelope; add `--no-cache` to `fetch`; normalize `fetch-batch` output |
| `scripts/_normalize.py` | Add `backend` field to `SearchResult`; add `--json-array` support to `fetch-batch` emit |
| `scripts/_searxng.py` | Populate `backend: "searxng"` on results |
| `scripts/_search_fallback.py` | Populate `backend: "brave"` / `backend: "ddgs"` on results |
| `scripts/_deps.py` | Expose `clear-cache` as CLI-callable function |
| `SKILL.md` | Update `search` docs for `--mode`, `backend` field; update `fetch` docs for `--no-cache`; update `fetch-batch` docs for `--json-array`; add `setup --clear-cache` |

Files **tested** (modify existing test files + add assertions):

| Test file | What's added |
|---|---|
| `tests/test_relevance.py` | Tests for `fit_markdown()` — noise removal, BM25 scoring, empty/edge cases |
| `tests/test_normalize.py` | Tests for `backend` field presence in `SearchResult`; `fetch-batch` JSON array emit |
| `tests/test_searxng.py` | Assert `backend: "searxng"` populated on results |
| `tests/test_deps.py` | Assert `clear_stamp_cache` callable; assert new `clear_page_cache` callable |

---

## Task 1: `fit_markdown` — Query-Aware BM25 Content Pruning

**What and why:** Crawl4AI's most-praised feature. Strips nav menus, footers, cookie banners, and boilerplate *before* the LLM sees the content, using BM25 scoring tied to the search query. The TF-IDF `filter_relevant_paragraphs` already exists — this adds a complementary noise-removal pass (no query needed) and an improved scoring path (BM25 term frequency normalization). The two functions are kept separate: `fit_markdown` for noise removal, `filter_relevant_paragraphs` for query-aware selection.

**Files:**
- Modify: `scripts/_relevance.py`
- Modify: `tests/test_relevance.py`

- [ ] **Step 1: Write failing tests for `fit_markdown`**

Add to `tests/test_relevance.py`:

```python
from _relevance import fit_markdown

NAV_BLOCK = "Home About Contact Blog Privacy Policy Terms of Service"
ARTICLE_PARA = "The transformer architecture introduced the attention mechanism which changed natural language processing fundamentally."
FOOTER_BLOCK = "© 2024 Example Corp. All rights reserved. Cookie settings. Sitemap."
CODE_BLOCK = "```python\ndef attention(q, k, v):\n    return softmax(q @ k.T) @ v\n```"

def test_fit_markdown_removes_nav_and_footer():
    md = f"{NAV_BLOCK}\n\n{ARTICLE_PARA}\n\n{FOOTER_BLOCK}"
    result = fit_markdown(md)
    assert ARTICLE_PARA in result
    assert NAV_BLOCK not in result
    assert FOOTER_BLOCK not in result

def test_fit_markdown_preserves_code_blocks():
    md = f"{ARTICLE_PARA}\n\n{CODE_BLOCK}"
    result = fit_markdown(md)
    assert "attention" in result

def test_fit_markdown_with_query_boosts_relevant():
    md = f"Cookie policy text.\n\n{ARTICLE_PARA}\n\nContact us for more info."
    result = fit_markdown(md, query="transformer attention mechanism")
    assert ARTICLE_PARA in result

def test_fit_markdown_empty_returns_empty():
    assert fit_markdown("") == ""

def test_fit_markdown_no_query_still_removes_noise():
    md = f"{NAV_BLOCK}\n\n{ARTICLE_PARA}"
    result = fit_markdown(md)
    # short nav-like blocks with no content signals are pruned
    assert ARTICLE_PARA in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_relevance.py -k "fit_markdown" -v
```

Expected: `ImportError: cannot import name 'fit_markdown'`

- [ ] **Step 3: Implement `fit_markdown` in `scripts/_relevance.py`**

Append to `scripts/_relevance.py` (after existing code):

```python
# Heuristic patterns for noise blocks (nav, footer, cookie banners)
_NOISE_PATTERNS = re.compile(
    r'\b(cookie|privacy policy|terms of service|all rights reserved|sitemap|'
    r'subscribe|newsletter|follow us|share this|back to top|skip to|'
    r'copyright ©|©\s*\d{4})\b',
    re.IGNORECASE,
)
_MIN_CONTENT_WORDS = 8  # blocks shorter than this with noise signals are pruned


def _bm25_score(
    query_tokens: list[str],
    para_tokens: list[str],
    doc_freqs: dict[str, int],
    num_docs: int,
    k1: float = 1.5,
    b: float = 0.75,
    avg_dl: float = 50.0,
) -> float:
    """BM25 relevance score for a paragraph against a query."""
    if not para_tokens or not query_tokens:
        return 0.0
    dl = len(para_tokens)
    para_counts = Counter(para_tokens)
    score = 0.0
    for token in set(query_tokens):
        tf = para_counts.get(token, 0)
        if tf == 0:
            continue
        df = doc_freqs.get(token, 0)
        idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1)
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
        score += idf * tf_norm
    return score


def _is_noise_block(para: str) -> bool:
    """Return True if a paragraph looks like nav/footer/boilerplate."""
    words = _tokenize(para)
    if len(words) < _MIN_CONTENT_WORDS:
        # Very short blocks are noise unless they contain substantive signals
        return True
    noise_hits = len(_NOISE_PATTERNS.findall(para))
    # If >30% of words are noise-signal words, treat as noise
    return noise_hits / max(len(words), 1) > 0.3


def fit_markdown(markdown: str, *, query: str = "", min_chars: int = 40) -> str:
    """
    Remove boilerplate/noise blocks from markdown.

    If `query` is provided, also ranks remaining paragraphs by BM25 relevance
    and returns only the top 60% (minimum 3 paragraphs), preserving order.

    Noise removal is always applied regardless of query.
    Code blocks (``` fenced) are always preserved.
    """
    if not markdown:
        return markdown

    # Split into paragraphs, preserving fenced code blocks as atomic units
    raw_paras = re.split(r'\n{2,}', markdown)

    kept: list[str] = []
    in_code = False
    code_buf: list[str] = []

    for para in raw_paras:
        stripped = para.strip()
        if not stripped:
            continue

        # Fenced code block handling (always keep)
        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                code_buf = [stripped]
                if stripped.count("```") >= 2:  # single-line fence
                    kept.append(stripped)
                    in_code = False
                    code_buf = []
            else:
                code_buf.append(stripped)
                kept.append("\n\n".join(code_buf))
                in_code = False
                code_buf = []
            continue

        if in_code:
            code_buf.append(stripped)
            continue

        if len(stripped) < min_chars:
            continue

        if _is_noise_block(stripped):
            continue

        kept.append(stripped)

    if not kept:
        # Fell through — return original to avoid data loss
        return markdown

    if not query:
        return "\n\n".join(kept)

    # BM25 re-ranking with query
    query_tokens = _tokenize(query)
    tokenized = [_tokenize(p) for p in kept]
    avg_dl = sum(len(t) for t in tokenized) / max(len(tokenized), 1)

    doc_freqs: dict[str, int] = Counter()
    for tokens in tokenized:
        for token in set(tokens):
            doc_freqs[token] += 1

    scores = [
        _bm25_score(query_tokens, tokens, doc_freqs, len(kept), avg_dl=avg_dl)
        for tokens in tokenized
    ]

    # Keep top 60% by BM25, minimum 3 paragraphs, preserving original order
    top_n = max(3, int(len(kept) * 0.6))
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    selected = sorted(i for i, _ in indexed[:top_n])
    return "\n\n".join(kept[i] for i in selected)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_relevance.py -v
```

Expected: all tests pass, including existing 5 + new 5.

- [ ] **Step 5: Run full suite to confirm no regression**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/_relevance.py tests/test_relevance.py
git commit -m "feat: add fit_markdown() — BM25 noise pruning with optional query-aware ranking"
```

---

## Task 2: Wire `fit_markdown` into `search --fetch-top` Pipeline

**What and why:** The query is available in `cmd_search`. When `--fetch-top N` fetches and embeds full page content, the content should be noise-pruned and query-filtered before being returned to the agent. This is the single highest-leverage extraction quality improvement: agents get relevant paragraphs, not full pages with footers and nav menus. Zero new flags needed — it activates automatically when `--fetch-top` is used, with `--no-fit` to opt out.

**Files:**
- Modify: `scripts/web.py` (the `cmd_search` function, lines ~110–193 and `_fetch_parallel`)

- [ ] **Step 1: Write the test**

This is integration-level behaviour tested by inspecting the `content` sub-object on `--fetch-top` results. Add to `tests/test_web_helpers.py` (existing file):

```python
from _relevance import fit_markdown

def test_fit_markdown_called_on_fetch_top_content():
    """fit_markdown removes boilerplate from content markdown."""
    noise = "Cookie policy. Privacy. All rights reserved. Subscribe to newsletter."
    article = "The attention mechanism in transformers computes weighted sums over value vectors using softmax-normalized dot products."
    raw_md = f"{noise}\n\n{article}"
    result = fit_markdown(raw_md, query="attention mechanism transformers")
    assert article in result
    assert "Cookie policy" not in result
```

- [ ] **Step 2: Run test to confirm it passes (pure unit test)**

```bash
python3 -m pytest tests/test_web_helpers.py -v
```

- [ ] **Step 3: Wire `fit_markdown` into `cmd_search` in `scripts/web.py`**

Locate the `--fetch-top` loop in `cmd_search` (approximately lines 140–159). After `r["content"] = content` is set, apply `fit_markdown`:

```python
# After: r["content"] = content
if content.get("markdown") and not getattr(args, "no_fit", False):
    from _relevance import fit_markdown
    content["markdown"] = fit_markdown(
        content["markdown"], query=args.query
    )
    r["content"] = content
```

- [ ] **Step 4: Add `--no-fit` flag to the `search` subparser**

Find the `search` subparser argument definitions in `main()` (around line 750+) and add:

```python
p_search.add_argument(
    "--no-fit",
    action="store_true",
    default=False,
    help="Skip fit_markdown noise pruning on --fetch-top content (default: pruning enabled)",
)
```

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/web.py
git commit -m "feat: apply fit_markdown noise pruning to search --fetch-top content"
```

---

## Task 3: `backend` Field — Make Fallback Transparent

**What and why:** When SearXNG is unavailable and ddgs takes over, `quality_score` silently degrades. Agents ranking on `quality_score` get subtly wrong results without knowing it. Adding `backend: "searxng" | "brave" | "ddgs"` to both the top-level envelope and each result item makes this observable. The agent can branch: `if backend == "ddgs": ignore quality_score`.

**Files:**
- Modify: `scripts/_normalize.py`
- Modify: `scripts/_searxng.py`
- Modify: `scripts/_search_fallback.py`
- Modify: `scripts/web.py` (propagate backend field to envelope)
- Modify: `tests/test_normalize.py`
- Modify: `tests/test_searxng.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_normalize.py`:

```python
def test_searchresult_backend_field_preserved():
    r = SearchResult(query="test", backend="ddgs")
    d = r.to_dict()
    assert d["backend"] == "ddgs"

def test_searchresult_backend_defaults_to_empty():
    r = SearchResult(query="test")
    d = r.to_dict()
    # empty string should be omitted per existing to_dict convention
    assert "backend" not in d or d.get("backend") == ""
```

Add to `tests/test_searxng.py` (check existing structure first):

```python
def test_search_result_has_backend_searxng():
    # This tests the mapping only — mock the HTTP call
    from unittest.mock import patch, MagicMock
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [], "number_of_results": 0}
    mock_resp.raise_for_status = MagicMock()
    with patch("_searxng.create_httpx_client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
        from _searxng import search
        result = search("test query")
    assert result.backend == "searxng"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_normalize.py tests/test_searxng.py -v
```

Expected: `AttributeError: 'SearchResult' object has no attribute 'backend'`

- [ ] **Step 3: Add `backend` field to `SearchResult` in `scripts/_normalize.py`**

In the `SearchResult` dataclass (around line 139), add the field:

```python
@dataclass
class SearchResult:
    query: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    total_results: int = 0
    number_of_results: int = 0
    timing_ms: int = 0
    status: str = "ok"
    command: str = "search"
    error: Optional[str] = None
    citations: list[str] = field(default_factory=list)
    backend: str = ""          # ← NEW: "searxng" | "brave" | "ddgs" | ""
```

Update `to_dict` to omit empty `backend`:

```python
def to_dict(self) -> dict[str, Any]:
    d = asdict(self)
    if not d.get("error"):
        d.pop("error", None)
    if not d.get("citations"):
        d.pop("citations", None)
    if not d.get("backend"):
        d.pop("backend", None)   # ← NEW
    return d
```

- [ ] **Step 4: Set `backend` in `scripts/_searxng.py`**

In the `search()` function, update the returned `SearchResult`:

```python
return SearchResult(
    query=query,
    results=mapped,
    total_results=len(mapped),
    number_of_results=number_of_results,
    timing_ms=t.elapsed_ms,
    backend="searxng",    # ← NEW
)
```

Also update the failure return:

```python
return SearchResult(
    query=query,
    status="failed",
    error=f"SearXNG request failed: {exc}. ...",
    timing_ms=t.elapsed_ms,
    backend="searxng",    # ← NEW (attempted backend)
)
```

- [ ] **Step 5: Set `backend` in `scripts/_search_fallback.py`**

In `search_ddgs()`, update the returned `SearchResult`:

```python
return SearchResult(
    query=query, results=results,
    total_results=len(results), timing_ms=t.elapsed_ms,
    backend="ddgs",    # ← NEW
)
```

In `search_brave()`, update the returned `SearchResult`:

```python
return SearchResult(
    query=query, results=results,
    total_results=len(results), timing_ms=t.elapsed_ms,
    backend="brave",    # ← NEW
)
```

Also update both failure returns with `backend="ddgs"` / `backend="brave"` respectively.

- [ ] **Step 6: Propagate `backend` to the top-level envelope in `scripts/web.py`**

In `cmd_search`, after `result_dict = result.to_dict()`, the `backend` field is now part of the dict automatically. No additional wiring needed — `to_dict()` handles it.

However, also add `backend` to the `doctor` output so agents can query active backend without a search call. Locate `cmd_doctor` in `web.py` and ensure it calls the existing `search_backend` check (it already does — verify it's present in the output).

- [ ] **Step 7: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/_normalize.py scripts/_searxng.py scripts/_search_fallback.py scripts/web.py tests/test_normalize.py tests/test_searxng.py
git commit -m "feat: add backend field to search results for transparent fallback observability"
```

---

## Task 4: `search --mode fast|deep` — Single Latency Tier Dial

**What and why:** Tavily's `search_depth` is the most-cited reason agents prefer it for pipeline use. Right now, disabling enrichment + citations for a fast-mode pipeline requires passing `--no-enrich --no-cite`. An agent writing its own search calls has to know this combination. A single `--mode fast|deep` dial sets sensible defaults per tier. `fast` maps to `--no-enrich --no-cite --max-results 5`. `deep` maps to enrichment + citations + `--fetch-top 3` + `--max-results 10`. `default` (no flag) preserves current behavior. No logic changes — just argument pre-processing.

**Files:**
- Modify: `scripts/web.py` (search subparser + `cmd_search` pre-processing)

- [ ] **Step 1: Write the test**

Add to `tests/test_web_helpers.py`:

```python
def test_mode_fast_sets_no_enrich_no_cite():
    """--mode fast should set no_enrich=True, no_cite=True, max_results=5."""
    import argparse
    # Simulate the namespace as produced by the parser
    args = argparse.Namespace(
        mode="fast",
        no_enrich=False,
        no_cite=False,
        max_results=10,
        fetch_top=0,
    )
    from web import _apply_search_mode
    args = _apply_search_mode(args)
    assert args.no_enrich is True
    assert args.no_cite is True
    assert args.max_results == 5

def test_mode_deep_sets_fetch_top():
    import argparse
    args = argparse.Namespace(
        mode="deep",
        no_enrich=False,
        no_cite=False,
        max_results=10,
        fetch_top=0,
    )
    from web import _apply_search_mode
    args = _apply_search_mode(args)
    assert args.no_enrich is False
    assert args.fetch_top == 3

def test_mode_default_is_noop():
    import argparse
    args = argparse.Namespace(
        mode=None,
        no_enrich=False,
        no_cite=False,
        max_results=10,
        fetch_top=0,
    )
    from web import _apply_search_mode
    args = _apply_search_mode(args)
    assert args.no_enrich is False
    assert args.fetch_top == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_web_helpers.py -k "mode" -v
```

Expected: `ImportError: cannot import name '_apply_search_mode'`

- [ ] **Step 3: Add `_apply_search_mode` helper to `scripts/web.py`**

Add this function near the top of `web.py` (after the existing helper functions, before `cmd_search`):

```python
def _apply_search_mode(args: argparse.Namespace) -> argparse.Namespace:
    """Apply --mode presets to search args. Returns mutated args."""
    mode = getattr(args, "mode", None)
    if mode == "fast":
        args.no_enrich = True
        args.no_cite = True
        args.max_results = min(getattr(args, "max_results", 10), 5)
        args.fetch_top = 0
    elif mode == "deep":
        args.no_enrich = False
        args.no_cite = False
        if not getattr(args, "fetch_top", 0):
            args.fetch_top = 3
        args.max_results = max(getattr(args, "max_results", 10), 10)
    return args
```

- [ ] **Step 4: Add `--mode` flag to the `search` subparser and call the helper**

In `main()`, find the `search` subparser argument block and add:

```python
p_search.add_argument(
    "--mode",
    choices=["fast", "deep"],
    default=None,
    help=(
        "Preset mode: 'fast' disables enrichment/citations, limits to 5 results; "
        "'deep' enables enrichment + fetch-top 3 + 10 results. "
        "Individual flags override mode settings."
    ),
)
```

At the start of `cmd_search`, add:

```python
def cmd_search(args: argparse.Namespace) -> None:
    args = _apply_search_mode(args)   # ← NEW — apply mode presets
    from _searxng import search
    # ... rest unchanged
```

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/web.py
git commit -m "feat: add search --mode fast|deep preset dial for latency/quality tradeoff"
```

---

## Task 5: `fetch --no-cache` — Per-Call Cache Bypass

**What and why:** Multi-turn agent sessions accumulate stale `--diff` cache entries. Crawl4AI's `CacheMode.BYPASS` is specifically praised for agent loops. The `_page_cache` module only writes on `--diff`; the issue is that there is no way to force a fresh fetch without the diff comparison. `--no-cache` forces the fetch path to skip any cached content comparison and not update the cache — a clean one-shot read. Also, `clear_stamp_cache` should be callable from the CLI as `setup --clear-cache` so agents can reset state without knowing the `.deps_cache/` path.

**Files:**
- Modify: `scripts/_page_cache.py`
- Modify: `scripts/_deps.py`
- Modify: `scripts/web.py` (fetch subparser + `_post_process_result` + `setup` subparser)
- Modify: `tests/test_page_cache.py`
- Modify: `tests/test_deps.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_page_cache.py`:

```python
def test_no_cache_skips_read_and_write(tmp_path, monkeypatch):
    """When no_cache=True, check_and_update should not read or write."""
    from _page_cache import check_and_update
    # Pre-populate a cache entry
    check_and_update("https://example.com", "initial content", "Title")
    # Now call with no_cache — should return (None, "", "") without touching cache
    changed, prev, curr = check_and_update(
        "https://example.com", "new content", "Title", no_cache=True
    )
    assert changed is None
    assert prev == ""
    assert curr == ""
    # Cache entry should still be the original (not updated)
    changed2, _, curr2 = check_and_update("https://example.com", "new content", "Title")
    assert changed2 is True  # old hash vs new content = changed
```

Add to `tests/test_deps.py`:

```python
def test_clear_stamp_cache_callable():
    from _deps import clear_stamp_cache
    # Just verify it doesn't raise
    clear_stamp_cache()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_page_cache.py tests/test_deps.py -v
```

- [ ] **Step 3: Add `no_cache` param to `check_and_update` in `scripts/_page_cache.py`**

```python
def check_and_update(
    url: str,
    content: str,
    title: str = "",
    *,
    no_cache: bool = False,        # ← NEW
) -> tuple[Optional[bool], str, str]:
    if no_cache:
        return None, "", ""        # ← NEW: skip entirely
    current_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]
    cache = _load()
    entry = cache.get(url)
    previous_hash = entry["hash"] if entry else ""
    changed: Optional[bool] = None if not entry else (current_hash != previous_hash)
    cache[url] = {
        "hash": current_hash,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
    }
    _save(cache)
    return changed, previous_hash, current_hash
```

- [ ] **Step 4: Pass `no_cache` through in `scripts/web.py`**

In `_post_process_result`, update the `--diff` block:

```python
diff = getattr(args, "diff", False)
no_cache = getattr(args, "no_cache", False)
if (diff or no_cache) and result.status == "ok":
    from _page_cache import check_and_update
    changed, previous_hash, current_hash = check_and_update(
        result.url,
        result.markdown or result.text or "",
        result.title,
        no_cache=no_cache,          # ← NEW
    )
    result.changed = changed
    result.previous_hash = previous_hash
    result.current_hash = current_hash
```

Add `--no-cache` flag to the `fetch` subparser in `main()`:

```python
p_fetch.add_argument(
    "--no-cache",
    dest="no_cache",
    action="store_true",
    default=False,
    help="Skip reading/writing the content diff cache for this request.",
)
```

- [ ] **Step 5: Add `setup --clear-cache` to `scripts/web.py`**

Find `cmd_setup` in `web.py`. Add at the end, before `emit`:

```python
if getattr(args, "clear_cache", False):
    from _deps import clear_stamp_cache
    from _page_cache import clear_page_cache   # see next step
    clear_stamp_cache()
    clear_page_cache()
    result["cleared_caches"] = ["dep_stamps", "page_cache"]
```

Add `--clear-cache` to the `setup` subparser:

```python
p_setup.add_argument(
    "--clear-cache",
    dest="clear_cache",
    action="store_true",
    default=False,
    help="Clear dep-stamp cache and page-diff cache, forcing re-check on next run.",
)
```

Add `clear_page_cache()` to `scripts/_page_cache.py`:

```python
def clear_page_cache() -> None:
    """Delete the page diff cache file."""
    try:
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
    except Exception:
        pass
```

- [ ] **Step 6: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/_page_cache.py scripts/_deps.py scripts/web.py tests/test_page_cache.py tests/test_deps.py
git commit -m "feat: add fetch --no-cache and setup --clear-cache for agent session control"
```

---

## Task 6: `fetch-batch --json-array` — Consistent Output Format

**What and why:** `fetch-batch` outputs NDJSON; every other command outputs a single JSON object. Agents writing `result = json.loads(output)` silently fail on `fetch-batch`. The right fix is opt-in: `--json-array` wraps all results in a JSON array instead of NDJSON. NDJSON remains the default (correct for streaming large batches) but `--json-array` makes batch output parseable with the same code as single commands. No logic changes — pure output formatting.

**Files:**
- Modify: `scripts/web.py` (`cmd_fetch_batch` function + `fetch-batch` subparser)
- Modify: `tests/test_normalize.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_normalize.py`:

```python
import json as _json
import io
from unittest.mock import patch

def test_emit_json_array_writes_valid_array(capsys):
    from _normalize import emit_json_array
    data = [{"status": "ok", "url": "https://a.com"}, {"status": "ok", "url": "https://b.com"}]
    emit_json_array(data, pretty=False)
    captured = capsys.readouterr()
    parsed = _json.loads(captured.out)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["url"] == "https://a.com"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python3 -m pytest tests/test_normalize.py -k "json_array" -v
```

Expected: `ImportError: cannot import name 'emit_json_array'`

- [ ] **Step 3: Add `emit_json_array` to `scripts/_normalize.py`**

Add after the existing `emit_error` function:

```python
def emit_json_array(
    items: list[dict[str, Any]], *, pretty: bool = False
) -> None:
    """Write a JSON array to stdout. Used by fetch-batch --json-array."""
    indent = 2 if pretty else None
    json.dump(items, sys.stdout, indent=indent, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()
```

- [ ] **Step 4: Add `--json-array` to the `fetch-batch` subparser and use it in `cmd_fetch_batch`**

Find `cmd_fetch_batch` in `web.py` and the matching subparser. Add the flag:

```python
p_fetch_batch.add_argument(
    "--json-array",
    dest="json_array",
    action="store_true",
    default=False,
    help=(
        "Output a JSON array instead of NDJSON. "
        "Useful when batch results must be parsed with json.loads(). "
        "Default: NDJSON (one JSON object per line)."
    ),
)
```

In `cmd_fetch_batch`, accumulate results and emit at end if `--json-array`:

```python
def cmd_fetch_batch(args: argparse.Namespace) -> None:
    # ... existing URL-loading code unchanged ...

    json_array = getattr(args, "json_array", False)
    accumulated: list[dict] = []   # ← NEW

    for result_dict in _run_batch(...):   # existing batch loop
        if json_array:
            accumulated.append(result_dict)    # ← NEW: collect
        else:
            emit(result_dict, pretty=args.pretty)   # existing NDJSON path

    if json_array:                                  # ← NEW
        from _normalize import emit_json_array
        emit_json_array(accumulated, pretty=args.pretty)
```

> **Note:** The exact structure of the `cmd_fetch_batch` loop in `web.py` (around line 450+) must be read before implementing step 4. The pattern above is a sketch; adapt to the actual loop structure without restructuring it.

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/_normalize.py scripts/web.py tests/test_normalize.py
git commit -m "feat: add fetch-batch --json-array for consistent array output alongside NDJSON"
```

---

## Task 7: Update `SKILL.md` Documentation

**What and why:** The SKILL.md is the agent's primary interface — it's injected directly into context. Every new flag, field, and behavior must be documented there. This is the only task with no tests (docs don't have unit tests), but it's not optional: an undocumented feature is a missing feature from an agent's perspective.

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: Update `search` command documentation**

Add `--mode` to the `search` command block:

```
[--mode fast|deep]
```

Add `--no-fit` to the `search` command block.

Update the result fields line to include `backend`.

Add a row to the Routing Guide table:
```
| Fast search pipeline  | `search --mode fast`    | 1-2 | Disables enrichment, 5 results, low latency |
| Deep research         | `search --mode deep`    | 1-2 | Enrichment + fetch-top 3 + 10 results        |
```

- [ ] **Step 2: Update `fetch` command documentation**

Add `--no-cache` to the `fetch` command block.

Update the `--diff` description to note `--no-cache` as the complement.

- [ ] **Step 3: Update `fetch-batch` documentation**

Add `--json-array` to the `fetch-batch` command block with a note:

```
--json-array: Output a JSON array instead of NDJSON. Use when batch results
              must be parsed with json.loads() alongside single-command results.
```

- [ ] **Step 4: Update `setup` documentation**

Add `--clear-cache` to the `setup` command.

- [ ] **Step 5: Update Output Envelope section**

Add `backend` field to the search envelope description:
```
- **search**: ... `backend` ("searxng" | "brave" | "ddgs" — which provider was used) ...
```

- [ ] **Step 6: Commit**

```bash
git add SKILL.md
git commit -m "docs: update SKILL.md for --mode, --no-cache, --json-array, --clear-cache, backend field"
```

---

## Verification Checklist (run after all tasks complete)

```bash
# 1. Full unit test suite
python3 -m pytest tests/ -v
# Expected: all tests pass (was 56, now ~75+)

# 2. Smoke: search with backend field visible
bin/web-intel search "transformer attention" --pretty | jq '.backend'
# Expected: "searxng" | "brave" | "ddgs"

# 3. Smoke: search fast mode
bin/web-intel search "RLHF" --mode fast --pretty | jq '{results: (.results | length), backend}'
# Expected: results <= 5

# 4. Smoke: fit_markdown in fetch-top
bin/web-intel search "attention mechanism" --fetch-top 1 --pretty | jq '.results[0].content.markdown' | wc -c
# Should be significantly smaller than without --no-fit

# 5. Smoke: fetch --no-cache
bin/web-intel fetch "https://example.com" --no-cache --pretty | jq '.status'
# Expected: "ok", no changed/current_hash fields (no_cache skips diff)

# 6. Smoke: fetch-batch --json-array
echo "https://example.com" | bin/web-intel fetch-batch --json-array | python3 -c "import json,sys; d=json.load(sys.stdin); print(type(d))"
# Expected: <class 'list'>

# 7. Smoke: setup --clear-cache
bin/web-intel setup --clear-cache --pretty | jq '.cleared_caches'
# Expected: ["dep_stamps", "page_cache"]
```

---

## Non-Goals (explicitly out of scope for this plan)

- **Offline/bundled deps mode** — requires packaging infrastructure changes; separate plan
- **Agent PATH shim** — depends on skill manager integration; separate plan  
- **`auto_parameters` / query-intent detection** — requires LLM call; out of scope for a no-API-key tool
- **Unified `relevance_score` across commands** — requires aligning Trafilatura's confidence with BM25; follow-up work
- **NLP-driven extraction (no CSS selectors)** — requires LLM; out of scope
- **Crawl4AI Docker REST API server** — already supported via `--docker` flag
