#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPTS_DIR.parent

sys.path.insert(0, str(_SCRIPTS_DIR))

from _normalize import emit, emit_error, Timer
from _normalize import extract_domain
from _config import get_logger

log = get_logger("web")


def _crawl4ai_docker_available() -> bool:
    import urllib.request
    from _config import CRAWL4AI_DOCKER_URL

    try:
        req = urllib.request.Request(f"{CRAWL4AI_DOCKER_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _fetch_parallel(urls: list[str], *, concurrency: int, timeout: int) -> list[dict]:
    import asyncio
    from _trafilatura_extract import fetch_and_extract

    sem = asyncio.Semaphore(concurrency)

    async def _fetch_one(url: str) -> dict:
        async with sem:
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(
                    None, lambda: fetch_and_extract(url, timeout=timeout)
                )
                return {
                    "status": result.status,
                    "markdown": result.markdown,
                    "confidence": result.confidence,
                    "timing_ms": result.timing_ms,
                    "fetch_mode": result.fetch_mode,
                    "error": result.error,
                }
            except Exception as exc:
                return {"status": "failed", "error": str(exc)}

    async def _run_all() -> list[dict]:
        return await asyncio.gather(*[_fetch_one(u) for u in urls])

    return asyncio.run(_run_all())


def _build_citation(result: "WebResult") -> dict:
    domain = result.site_name or extract_domain(result.url)
    date = result.published_at or ""
    authors = result.authors or []
    title = result.title or result.url
    url = result.url

    parts = [f'"{title}"']
    if authors:
        parts.insert(0, ", ".join(authors) + ".")
    if domain:
        parts.append(domain + ".")
    parts.append(f"{date}." if date else "(date unknown).")
    parts.append(url)

    return {
        "url": url,
        "title": title,
        "site_name": domain,
        "published_at": date,
        "authors": authors,
        "citation_text": " ".join(p for p in parts if p),
    }


def _append_citation_to_markdown(result: "WebResult") -> None:
    if not result.markdown:
        return
    domain = result.site_name or extract_domain(result.url)
    date = result.published_at or ""
    authors = result.authors or []
    title = result.title or result.url
    url = result.url

    parts = [f"[{title}]({url})"]
    if domain:
        parts.append(f"· {domain}")
    if date:
        parts.append(f"· Published {date}")
    else:
        parts.append("· (date unknown)")
    if authors:
        parts.append(f"· By {', '.join(authors)}")

    result.markdown = result.markdown.rstrip() + f"\n\n---\n**Source:** {' '.join(parts)}"


def cmd_search(args: argparse.Namespace) -> None:
    from _searxng import search

    result = search(
        args.query,
        engines=args.engines,
        categories=args.categories,
        language=args.language,
        time_range=args.time_range,
        max_results=args.max_results,
        pageno=args.pageno,
        no_rerank=getattr(args, "no_rerank", False),
    )

    if result.status == "failed" and not getattr(args, "no_fallback", False):
        import os
        from _search_fallback import search_brave, search_ddgs

        brave_key = os.environ.get("BRAVE_API_KEY")
        if brave_key:
            log.info("SearXNG unavailable, trying Brave Search API fallback")
            result = search_brave(args.query, api_key=brave_key, max_results=args.max_results)

        if result.status == "failed":
            log.info("SearXNG unavailable, trying ddgs multi-engine fallback")
            result = search_ddgs(args.query, max_results=args.max_results)

        if result.status != "failed":
            result.error = (result.error or "") + " [SearXNG unavailable, used fallback]"

    fetch_top = getattr(args, "fetch_top", 0)
    if fetch_top > 0 and result.status != "failed" and result.results:
        top_urls = [r["url"] for r in result.results[:fetch_top] if r.get("url")]
        fetched = _fetch_parallel(
            top_urls,
            concurrency=getattr(args, "fetch_concurrency", 3),
            timeout=getattr(args, "fetch_timeout", 20),
        )
        for r, content in zip(result.results[:fetch_top], fetched):
            if content.get("error") is None:
                content.pop("error", None)
            r["content"] = content
            if content.get("markdown") and not getattr(args, "no_fit", False):
                from _relevance import fit_markdown
                content["markdown"] = fit_markdown(
                    content["markdown"], query=args.query
                )
                r["content"] = content
            if not r.get("published_at") and content.get("published_at"):
                r["published_at"] = content["published_at"]
                r.setdefault("meta_enriched", []).append("published_at")
                r["meta_source"] = "fetch"
            if not r.get("authors") and content.get("authors"):
                r["authors"] = content["authors"]
                r.setdefault("meta_enriched", []).append("authors")
                r.setdefault("meta_source", "fetch")

    if not getattr(args, "no_enrich", False) and result.status != "failed" and result.results:
        from _meta_enrichment import enrich_search_results
        enrich_search_results(
            result.results,
            concurrency=getattr(args, "enrich_concurrency", 5),
            timeout=getattr(args, "enrich_timeout", 8),
        )

    result_dict = result.to_dict()
    if not getattr(args, "no_cite", False) and result.results:
        citations = []
        for i, r in enumerate(result.results, start=1):
            r["citation_index"] = i
            domain = r.get("domain", "")
            date = r.get("published_at", "")
            authors = r.get("authors", [])
            title = r.get("title", r.get("url", ""))
            url = r.get("url", "")
            parts = [f"[{i}]", title]
            if authors:
                parts.append(f"by {', '.join(authors)}")
            if domain:
                parts.append(f"— {domain}")
            if date:
                parts.append(f"({date})")
            else:
                parts.append("(date unknown)")
            parts.append(url)
            citations.append(" ".join(p for p in parts if p))
        result_dict["citations"] = citations
        result_dict["results"] = result.results

    emit(result_dict, pretty=args.pretty)


_FETCH_FALLBACK_SIGNALS = (
    "javascript",
    "js-rendered",
    "dynamic content",
    "empty content",
    "requires javascript",
)


def _apply_token_limit(result: "WebResult", max_tokens: int) -> "WebResult":
    if max_tokens <= 0:
        return result
    char_limit = max_tokens * 4
    result.char_count = len(result.markdown or result.text or "")
    if result.markdown and len(result.markdown) > char_limit:
        result.markdown = result.markdown[:char_limit] + "\n\n[...truncated]"
        result.truncated = True
    if result.text and len(result.text) > char_limit:
        result.text = result.text[:char_limit] + "\n[...truncated]"
        result.truncated = True
    return result


def _apply_chunking(result: "WebResult", chunk_tokens: int, chunk_index: int) -> "WebResult":
    if chunk_tokens <= 0:
        return result
    char_size = chunk_tokens * 4
    content = result.markdown or result.text or ""
    if not content:
        return result

    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= char_size:
            chunks.append(remaining)
            break
        boundary = remaining.rfind("\n\n", 0, char_size)
        if boundary == -1 or boundary < char_size // 2:
            boundary = char_size
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()

    result.chunk_count = len(chunks)
    result.chunk_tokens = chunk_tokens
    safe_index = max(0, min(chunk_index, len(chunks) - 1))
    result.chunk_index = safe_index

    chunk_content = chunks[safe_index] if chunks else ""
    if result.markdown:
        result.markdown = chunk_content
    if result.text:
        result.text = chunk_content
    return result


def _post_process_result(result: "WebResult", args: argparse.Namespace) -> "WebResult":
    chunk_tokens = getattr(args, "chunk_tokens", 0)
    chunk_index = getattr(args, "chunk_index", 0)
    max_tokens = getattr(args, "max_tokens", 0)

    if chunk_tokens > 0:
        result = _apply_chunking(result, chunk_tokens, chunk_index)
    elif max_tokens > 0:
        result = _apply_token_limit(result, max_tokens)

    relevant_to = getattr(args, "relevant_to", "")
    if relevant_to and result.markdown:
        from _relevance import filter_relevant_paragraphs
        relevant_top = getattr(args, "relevant_top", 10)
        result.markdown = filter_relevant_paragraphs(result.markdown, relevant_to, top_n=relevant_top)
        if result.text:
            result.text = filter_relevant_paragraphs(result.text, relevant_to, top_n=relevant_top)

    diff = getattr(args, "diff", False)
    if diff and result.status == "ok":
        from _page_cache import check_and_update
        changed, previous_hash, current_hash = check_and_update(
            result.url, result.markdown or result.text or "", result.title
        )
        result.changed = changed
        result.previous_hash = previous_hash
        result.current_hash = current_hash

    return result


def _should_fallback_to_crawl(result: "WebResult") -> bool:
    if result.status not in ("failed", "partial"):
        return False
    if not result.markdown and not result.text:
        return True
    error_lower = (result.error or "").lower()
    return any(sig in error_lower for sig in _FETCH_FALLBACK_SIGNALS)


def cmd_fetch(args: argparse.Namespace) -> None:
    from _trafilatura_extract import fetch_and_extract

    result = fetch_and_extract(
        args.url,
        include_tables=args.include_tables,
        include_links=args.include_links,
        include_images=args.include_images,
        include_comments=args.include_comments,
        favor_precision=args.favor_precision,
        favor_recall=args.favor_recall,
        output_format=args.output_format,
        timeout=args.timeout,
    )

    if args.fallback_crawl and _should_fallback_to_crawl(result):
        try:
            from _crawl4ai_crawl import crawl
        except ImportError:
            result.error = (
                (result.error or "")
                + " | crawl4ai fallback unavailable: run 'setup --tier all'"
            )
            result.status = "partial"
        else:
            crawl_result = crawl(args.url, timeout=args.timeout)
            if crawl_result.status == "ok" and crawl_result.markdown:
                result = crawl_result

    if getattr(args, "wait_for_text", "") and result.status == "ok":
        import time
        target = args.wait_for_text.lower()
        for _ in range(getattr(args, "wait_for_retries", 3)):
            content = (result.markdown or result.text or "").lower()
            if target in content:
                break
            time.sleep(getattr(args, "wait_for_delay", 2.0))
            result = fetch_and_extract(
                args.url,
                include_tables=args.include_tables,
                include_links=args.include_links,
                output_format=args.output_format,
                timeout=args.timeout,
            )

    result.command = "fetch"
    result = _post_process_result(result, args)
    result.citation = _build_citation(result)
    _append_citation_to_markdown(result)
    emit(result.to_dict(), pretty=args.pretty)


def cmd_crawl(args: argparse.Namespace) -> None:
    from _crawl4ai_crawl import crawl

    use_docker = args.docker or (not args.docker and _crawl4ai_docker_available())
    result = crawl(
        args.url,
        wait_for=args.wait_for,
        screenshot=args.screenshot,
        pdf=args.pdf,
        execute_js=args.execute_js,
        timeout=args.timeout,
        headless=args.headless,
        use_docker=use_docker,
    )
    result.command = "crawl"
    result = _post_process_result(result, args)
    emit(result.to_dict(), pretty=args.pretty)


def cmd_scrape(args: argparse.Namespace) -> None:
    from _httpx_fetch import fetch
    from _bs4_scrape import scrape_selector, scrape_tables, scrape_lists, scrape_schema

    use_crawl4ai = args.use_crawl4ai or _crawl4ai_docker_available()

    if use_crawl4ai:
        try:
            from _crawl4ai_crawl import get_raw_html
        except ImportError:
            use_crawl4ai = False

    if use_crawl4ai:
        html = get_raw_html(
            args.url,
            wait_for=getattr(args, "wait_for", None),
            timeout=getattr(args, "timeout", 60),
            use_docker=_crawl4ai_docker_available(),
        )
        fetch_mode = "crawl4ai"
    else:
        try:
            html, _, _ = fetch(args.url)
            fetch_mode = "httpx"
        except Exception as exc:
            emit_error("scrape", f"Fetch failed: {exc}", pretty=args.pretty)
            return

    if not html:
        emit_error("scrape", "Empty response from server", pretty=args.pretty)
        return

    schema_str = getattr(args, "schema", "")
    if schema_str:
        import json as _json
        try:
            schema = _json.loads(schema_str)
        except _json.JSONDecodeError as exc:
            emit_error("scrape", f"Invalid --schema JSON: {exc}", pretty=args.pretty)
            return
        result = scrape_schema(html, schema, url=args.url)
    elif args.table:
        result = scrape_tables(html, url=args.url)
    elif args.list:
        result = scrape_lists(html, url=args.url)
    elif args.selector:
        result = scrape_selector(
            html, args.selector, url=args.url, attribute=args.attribute
        )
    else:
        emit_error(
            "scrape", "Provide --selector, --table, --list, or --schema", pretty=args.pretty
        )
        return

    result.command = "scrape"
    result.fetch_mode = fetch_mode
    emit(result.to_dict(), pretty=args.pretty)


def cmd_extract(args: argparse.Namespace) -> None:
    from _trafilatura_extract import extract_from_html

    if args.stdin:
        html = sys.stdin.read()
    elif args.html_file:
        with open(args.html_file) as f:
            html = f.read()
    else:
        emit_error("extract", "Provide --html-file or --stdin", pretty=args.pretty)
        return

    result = extract_from_html(
        html,
        url=args.url or "",
        include_tables=args.include_tables,
        include_links=args.include_links,
        output_format=args.output_format,
    )
    result.command = "extract"
    result.fetch_mode = "local"
    result = _post_process_result(result, args)
    emit(result.to_dict(), pretty=args.pretty)


def cmd_discover(args: argparse.Namespace) -> None:
    from _trafilatura_extract import discover_sitemap, discover_sitemap_enriched, discover_crawl

    enriched = getattr(args, "enriched", False)

    if args.mode in ("sitemap", "both"):
        if enriched:
            result = discover_sitemap_enriched(args.url, max_urls=args.max_urls)
        else:
            result = discover_sitemap(
                args.url,
                target_lang=args.language,
                max_urls=args.max_urls,
            )
        if args.mode == "both":
            crawl_result = discover_crawl(
                args.url,
                max_urls=args.max_urls,
                language=args.language,
            )
            seen = set(result.urls)
            for u in crawl_result.urls:
                if u not in seen:
                    result.urls.append(u)
                    seen.add(u)
            for entry in crawl_result.url_entries:
                if entry["url"] not in {e["url"] for e in result.url_entries}:
                    result.url_entries.append(entry)
            result.total_urls = len(result.urls)
            result.mode = "both"
            result.timing_ms += crawl_result.timing_ms
    else:
        result = discover_crawl(
            args.url,
            max_urls=args.max_urls,
            language=args.language,
        )

    emit(result.to_dict(), pretty=args.pretty)


def cmd_fetch_batch(args: argparse.Namespace) -> None:
    import asyncio
    from pathlib import Path as _Path
    from urllib.parse import urlparse as _urlparse
    import time as _time
    from _trafilatura_extract import fetch_and_extract

    if args.url_file:
        urls = _Path(args.url_file).read_text().splitlines()
    else:
        urls = sys.stdin.read().splitlines()
    urls = [u.strip() for u in urls if u.strip()]

    if not urls:
        emit_error("fetch-batch", "No URLs provided", pretty=args.pretty)
        return

    sem = asyncio.Semaphore(args.concurrency)
    domain_last: dict[str, float] = {}

    async def _fetch_one(url: str) -> None:
        async with sem:
            domain = _urlparse(url).netloc
            if args.domain_delay > 0 and domain in domain_last:
                wait = args.domain_delay - (_time.monotonic() - domain_last[domain])
                if wait > 0:
                    await asyncio.sleep(wait)
            domain_last[domain] = _time.monotonic()

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: fetch_and_extract(url, timeout=args.timeout)
            )
            result.command = "fetch-batch"
            if args.max_tokens:
                result = _apply_token_limit(result, args.max_tokens)
            result.citation = _build_citation(result)
            emit(result.to_dict(), pretty=False)

    async def _run() -> None:
        await asyncio.gather(*[_fetch_one(u) for u in urls])

    asyncio.run(_run())


def cmd_doctor(args: argparse.Namespace) -> None:
    import importlib
    import os
    import shutil
    import subprocess

    checks: list[dict] = []

    # 1. Python version
    ver = sys.version_info
    py_ok = ver >= (3, 9) and ver < (3, 14)
    checks.append(
        {
            "check": "python_version",
            "status": "ok" if py_ok else "warn",
            "detail": f"{ver.major}.{ver.minor}.{ver.micro}",
            "hint": "Python 3.14+ may break some deps. Use 3.11-3.13."
            if not py_ok
            else "",
        }
    )

    # 2. Core Python deps
    from _deps import CORE_DEPS, CRAWL_DEPS, _import_name

    for pkg in CORE_DEPS:
        mod = _import_name(pkg)
        try:
            importlib.import_module(mod)
            checks.append({"check": f"python_dep:{pkg}", "status": "ok"})
        except ImportError:
            checks.append(
                {
                    "check": f"python_dep:{pkg}",
                    "status": "missing",
                    "hint": f"pip install '{pkg}'",
                }
            )

    # 3. Crawl4AI dep
    for pkg in CRAWL_DEPS:
        mod = _import_name(pkg)
        try:
            importlib.import_module(mod)
            checks.append({"check": f"python_dep:{pkg}", "status": "ok"})
        except ImportError:
            checks.append(
                {
                    "check": f"python_dep:{pkg}",
                    "status": "missing",
                    "hint": f"pip install '{pkg}' && crawl4ai-setup",
                }
            )

    # 4. Docker available
    docker_ok = shutil.which("docker") is not None
    checks.append(
        {
            "check": "docker",
            "status": "ok" if docker_ok else "missing",
            "hint": ""
            if docker_ok
            else "Install Docker: https://docs.docker.com/get-docker/",
        }
    )

    # 5. SearXNG running
    searxng_ok = False
    if docker_ok:
        try:
            out = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=wrs-searxng",
                    "--format",
                    "{{.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            searxng_ok = "Up" in out.stdout
        except Exception:
            pass
    checks.append(
        {
            "check": "searxng_docker",
            "status": "ok" if searxng_ok else "not_running",
            "hint": ""
            if searxng_ok
            else f"docker compose -f {_SKILL_DIR}/docker/docker-compose.searxng.yml up -d",
        }
    )

    # 6. SearXNG API reachable
    searxng_api_ok = False
    if searxng_ok:
        try:
            from _config import SEARXNG_URL
            import urllib.request

            req = urllib.request.Request(
                f"{SEARXNG_URL}/search?q=test&format=json", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                searxng_api_ok = resp.status == 200
        except Exception:
            pass
    checks.append(
        {
            "check": "searxng_api",
            "status": "ok"
            if searxng_api_ok
            else ("skip" if not searxng_ok else "fail"),
            "hint": ""
            if searxng_api_ok
            else "Ensure 'json' is in search.formats in docker/searxng/settings.yml",
        }
    )

    brave_key = os.environ.get("BRAVE_API_KEY")
    checks.append({
        "check": "search_fallback_brave",
        "status": "ok" if brave_key else "optional",
        "hint": "" if brave_key else "Set BRAVE_API_KEY in .env for a higher-quality keyed search fallback",
    })

    ddgs_ok = False
    try:
        importlib.import_module("ddgs")
        ddgs_ok = True
    except ImportError:
        pass
    checks.append({
        "check": "search_fallback_ddgs",
        "status": "ok" if ddgs_ok else "not_installed",
        "hint": "" if ddgs_ok else "Run: pip install ddgs  (zero-config multi-engine fallback)",
    })

    # 7. Crawl4AI Docker container running
    crawl4ai_docker_ok = False
    if docker_ok:
        try:
            out = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=wrs-crawl4ai",
                    "--format",
                    "{{.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            crawl4ai_docker_ok = "Up" in out.stdout
        except Exception:
            pass
    checks.append(
        {
            "check": "crawl4ai_docker",
            "status": "ok" if crawl4ai_docker_ok else "not_running",
            "hint": ""
            if crawl4ai_docker_ok
            else f"docker compose -f {_SKILL_DIR}/docker/docker-compose.yml up -d crawl4ai",
        }
    )

    # 8. Crawl4AI Docker API reachable
    crawl4ai_api_ok = False
    if crawl4ai_docker_ok:
        try:
            from _config import CRAWL4AI_DOCKER_URL
            import urllib.request

            req = urllib.request.Request(
                f"{CRAWL4AI_DOCKER_URL}/health", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                crawl4ai_api_ok = resp.status == 200
        except Exception:
            pass
    checks.append(
        {
            "check": "crawl4ai_api",
            "status": "ok"
            if crawl4ai_api_ok
            else ("skip" if not crawl4ai_docker_ok else "fail"),
            "hint": ""
            if crawl4ai_api_ok
            else f"Check crawl4ai container logs: docker logs wrs-crawl4ai",
        }
    )

    # 9. Crawl4AI local browser
    crawl4ai_browser_ok = False
    try:
        playwright_paths = [
            Path.home() / ".cache" / "ms-playwright",           # Linux
            Path.home() / "Library" / "Caches" / "ms-playwright",  # macOS
            Path.home() / "AppData" / "Local" / "ms-playwright",    # Windows
        ]
        for playwright_path in playwright_paths:
            if playwright_path.exists() and any(playwright_path.iterdir()):
                crawl4ai_browser_ok = True
                break
    except Exception:
        pass
    if not crawl4ai_browser_ok:
        try:
            import crawl4ai  # noqa: F401

            # If crawl4ai is importable, check if setup was run
            crawl4ai_setup = shutil.which("crawl4ai-setup")
            checks.append(
                {
                    "check": "crawl4ai_browser",
                    "status": "not_setup",
                    "hint": "Run: crawl4ai-setup"
                    if crawl4ai_setup
                    else "pip install crawl4ai && crawl4ai-setup",
                }
            )
        except ImportError:
            checks.append(
                {
                    "check": "crawl4ai_browser",
                    "status": "skip",
                    "hint": "Install crawl4ai first",
                }
            )
    else:
        checks.append({"check": "crawl4ai_browser", "status": "ok"})

    # 10. .env file
    env_file = _SKILL_DIR / ".env"
    checks.append(
        {
            "check": "env_file",
            "status": "ok" if env_file.exists() else "missing",
            "hint": ""
            if env_file.exists()
            else f"cp {_SKILL_DIR}/.env.example {_SKILL_DIR}/.env",
        }
    )

    # Summary
    all_ok = all(c["status"] == "ok" for c in checks)
    ready_tiers = []
    core_deps_ok = all(
        c["status"] == "ok"
        for c in checks
        if c["check"].startswith("python_dep:") and "crawl4ai" not in c["check"]
    )
    if core_deps_ok:
        ready_tiers.extend(["fetch", "extract", "discover", "scrape"])
    search_ready = (
        (searxng_api_ok and core_deps_ok)
        or (brave_key and core_deps_ok)
        or (ddgs_ok and core_deps_ok)
    )
    if search_ready:
        ready_tiers.append("search")
    if crawl4ai_api_ok and core_deps_ok:
        ready_tiers.append("crawl")
    elif crawl4ai_browser_ok and core_deps_ok:
        ready_tiers.append("crawl")

    search_backend = (
        "searxng" if searxng_api_ok
        else "brave" if brave_key
        else "ddgs" if ddgs_ok
        else "none"
    )

    emit(
        {
            "status": "ok" if all_ok else "partial",
            "command": "doctor",
            "skill_dir": str(_SKILL_DIR),
            "search_backend": search_backend,
            "ready_commands": ready_tiers,
            "checks": [{k: v for k, v in c.items() if v} for c in checks],
        },
        pretty=args.pretty,
    )


def cmd_setup(args: argparse.Namespace) -> None:
    """Auto-setup: install deps, start SearXNG, configure .env."""
    import shutil
    import subprocess

    steps: list[dict] = []

    # 1. .env file
    env_file = _SKILL_DIR / ".env"
    env_example = _SKILL_DIR / ".env.example"
    if not env_file.exists() and env_example.exists():
        import shutil as sh

        sh.copy2(env_example, env_file)
        steps.append({"step": "env_file", "status": "created", "path": str(env_file)})
    else:
        steps.append(
            {
                "step": "env_file",
                "status": "exists" if env_file.exists() else "no_template",
            }
        )

    # 2. Install Python deps for the requested tier
    tier = getattr(args, "tier", "core")
    from _deps import ensure_deps, CORE_DEPS, CRAWL_DEPS

    try:
        if tier == "all":
            ensure_deps("fetch")
        else:
            ensure_deps("scrape")  # scrape requires all CORE_DEPS
        steps.append({"step": "python_deps", "status": "ok", "tier": tier})
    except SystemExit:
        steps.append(
            {
                "step": "python_deps",
                "status": "failed",
                "hint": "Try: pip install " + " ".join(CORE_DEPS),
            }
        )

    # 3. Start SearXNG if Docker available and not running
    if shutil.which("docker"):
        try:
            out = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=wrs-searxng",
                    "--format",
                    "{{.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "Up" not in out.stdout:
                compose_file = _SKILL_DIR / "docker" / "docker-compose.searxng.yml"
                subprocess.run(
                    ["docker", "compose", "-f", str(compose_file), "up", "-d"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                steps.append({"step": "searxng", "status": "started"})
            else:
                steps.append({"step": "searxng", "status": "already_running"})
        except Exception as exc:
            steps.append({"step": "searxng", "status": "failed", "error": str(exc)})
    else:
        steps.append({"step": "searxng", "status": "skip", "hint": "Docker not found"})

    # 4. Start Crawl4AI Docker container (only if tier=all)
    if tier == "all" and shutil.which("docker"):
        try:
            out = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=wrs-crawl4ai",
                    "--format",
                    "{{.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "Up" not in out.stdout:
                compose_file = _SKILL_DIR / "docker" / "docker-compose.yml"
                subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "up",
                        "-d",
                        "crawl4ai",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                steps.append({"step": "crawl4ai_docker", "status": "started"})
            else:
                steps.append({"step": "crawl4ai_docker", "status": "already_running"})
        except Exception as exc:
            steps.append(
                {"step": "crawl4ai_docker", "status": "failed", "error": str(exc)}
            )
    elif tier == "all":
        steps.append(
            {"step": "crawl4ai_docker", "status": "skip", "hint": "Docker not found"}
        )

    # 5. Crawl4AI local browser setup (only if tier=all)
    if tier == "all":
        crawl4ai_setup_bin = shutil.which("crawl4ai-setup")
        if crawl4ai_setup_bin:
            try:
                subprocess.run([crawl4ai_setup_bin], capture_output=True, timeout=300)
                steps.append({"step": "crawl4ai_browser", "status": "ok"})
            except Exception as exc:
                steps.append(
                    {"step": "crawl4ai_browser", "status": "failed", "error": str(exc)}
                )
        else:
            steps.append(
                {
                    "step": "crawl4ai_browser",
                    "status": "skip",
                    "hint": "crawl4ai not installed",
                }
            )

    emit(
        {
            "status": "ok"
            if all(
                s["status"] in ("ok", "exists", "created", "already_running", "started")
                for s in steps
            )
            else "partial",
            "command": "setup",
            "steps": steps,
        },
        pretty=args.pretty,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web.py",
        description="Web research stack — search, fetch, crawl, scrape, extract, discover",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--engines", default="")
    p_search.add_argument("--categories", default="general")
    p_search.add_argument("--language", default="en")
    p_search.add_argument("--time-range", dest="time_range", default="")
    p_search.add_argument("--max-results", dest="max_results", type=int, default=10)
    p_search.add_argument("--pageno", type=int, default=1)
    p_search.add_argument("--no-rerank", dest="no_rerank", action="store_true",
                          help="Preserve SearXNG result order, don't rerank by quality_score")
    p_search.add_argument("--no-fallback", dest="no_fallback", action="store_true",
                          help="Fail immediately if SearXNG unavailable, skip fallback backends")
    p_search.add_argument("--fetch-top", dest="fetch_top", type=int, default=0,
                          help="Fetch and extract content from top N results")
    p_search.add_argument("--fetch-concurrency", dest="fetch_concurrency", type=int, default=3)
    p_search.add_argument("--fetch-timeout", dest="fetch_timeout", type=int, default=20)
    p_search.add_argument("--no-enrich", dest="no_enrich", action="store_true", default=False,
                          help="Skip head-fetch enrichment for missing published_at/authors. Faster; sourcing may be incomplete.")
    p_search.add_argument("--no-cite", dest="no_cite", action="store_true", default=False,
                          help="Omit citations[] array and citation_index from output.")
    p_search.add_argument("--enrich-concurrency", dest="enrich_concurrency", type=int, default=5,
                          help="Max concurrent head-fetch requests for metadata enrichment (default: 5).")
    p_search.add_argument("--enrich-timeout", dest="enrich_timeout", type=int, default=8,
                          help="Per-request timeout in seconds for enrichment head-fetches (default: 8).")
    p_search.add_argument("--pretty", action="store_true")
    p_search.add_argument(
        "--no-fit",
        dest="no_fit",
        action="store_true",
        default=False,
        help="Skip fit_markdown noise pruning on --fetch-top content (default: pruning enabled)",
    )
    p_search.set_defaults(func=cmd_search)

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("url")
    p_fetch.add_argument(
        "--no-extract", dest="extract", action="store_false", default=True
    )
    p_fetch.add_argument("--include-tables", action="store_true")
    p_fetch.add_argument("--include-links", action="store_true")
    p_fetch.add_argument("--include-images", action="store_true")
    p_fetch.add_argument("--include-comments", action="store_true")
    p_fetch.add_argument("--favor-precision", action="store_true")
    p_fetch.add_argument("--favor-recall", action="store_true")
    p_fetch.add_argument("--output-format", dest="output_format", default="markdown")
    p_fetch.add_argument(
        "--no-fallback-crawl", dest="fallback_crawl", action="store_false", default=True
    )
    p_fetch.add_argument("--timeout", type=int, default=30)
    p_fetch.add_argument("--max-tokens", dest="max_tokens", type=int, default=0,
                         help="Truncate markdown/text to approximately N tokens (1 token ≈ 4 chars)")
    p_fetch.add_argument("--chunk-tokens", dest="chunk_tokens", type=int, default=0,
                         help="Split content into chunks of ~N tokens each")
    p_fetch.add_argument("--chunk-index", dest="chunk_index", type=int, default=0,
                         help="Which chunk to return (0-based). Requires --chunk-tokens.")
    p_fetch.add_argument("--relevant-to", dest="relevant_to", default="",
                         help="Filter content to paragraphs most relevant to this query")
    p_fetch.add_argument("--relevant-top", dest="relevant_top", type=int, default=10)
    p_fetch.add_argument("--wait-for-text", dest="wait_for_text", default="",
                         help="Retry httpx fetch until this text appears (static pages only; use crawl for JS)")
    p_fetch.add_argument("--wait-for-retries", dest="wait_for_retries", type=int, default=3)
    p_fetch.add_argument("--wait-for-delay", dest="wait_for_delay", type=float, default=2.0)
    p_fetch.add_argument("--diff", action="store_true",
                         help="Compare content to cached version and report changes")
    p_fetch.add_argument("--pretty", action="store_true")
    p_fetch.set_defaults(func=cmd_fetch)

    p_crawl = sub.add_parser("crawl")
    p_crawl.add_argument("url")
    p_crawl.add_argument("--wait-for", dest="wait_for")
    p_crawl.add_argument("--screenshot", action="store_true")
    p_crawl.add_argument("--pdf", action="store_true")
    p_crawl.add_argument("--execute-js", dest="execute_js")
    p_crawl.add_argument("--timeout", type=int, default=60)
    p_crawl.add_argument(
        "--no-headless", dest="headless", action="store_false", default=True
    )
    p_crawl.add_argument("--docker", action="store_true")
    p_crawl.add_argument("--max-tokens", dest="max_tokens", type=int, default=0)
    p_crawl.add_argument("--chunk-tokens", dest="chunk_tokens", type=int, default=0)
    p_crawl.add_argument("--chunk-index", dest="chunk_index", type=int, default=0)
    p_crawl.add_argument("--relevant-to", dest="relevant_to", default="")
    p_crawl.add_argument("--relevant-top", dest="relevant_top", type=int, default=10)
    p_crawl.add_argument("--pretty", action="store_true")
    p_crawl.set_defaults(func=cmd_crawl)

    p_scrape = sub.add_parser("scrape")
    p_scrape.add_argument("url")
    p_scrape.add_argument("--selector")
    p_scrape.add_argument("--attribute")
    p_scrape.add_argument("--table", action="store_true")
    p_scrape.add_argument("--list", action="store_true")
    p_scrape.add_argument("--schema", default="",
                          help='JSON schema: {"field": "css-selector", ...}')
    p_scrape.add_argument("--use-crawl4ai", action="store_true")
    p_scrape.add_argument("--timeout", type=int, default=60)
    p_scrape.add_argument("--pretty", action="store_true")
    p_scrape.set_defaults(func=cmd_scrape)

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--html-file", dest="html_file")
    p_extract.add_argument("--stdin", action="store_true")
    p_extract.add_argument("--url", default="")
    p_extract.add_argument("--include-tables", action="store_true")
    p_extract.add_argument("--include-links", action="store_true")
    p_extract.add_argument("--output-format", dest="output_format", default="markdown")
    p_extract.add_argument("--max-tokens", dest="max_tokens", type=int, default=0)
    p_extract.add_argument("--chunk-tokens", dest="chunk_tokens", type=int, default=0)
    p_extract.add_argument("--chunk-index", dest="chunk_index", type=int, default=0)
    p_extract.add_argument("--relevant-to", dest="relevant_to", default="")
    p_extract.add_argument("--relevant-top", dest="relevant_top", type=int, default=10)
    p_extract.add_argument("--pretty", action="store_true")
    p_extract.set_defaults(func=cmd_extract)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("url")
    p_discover.add_argument(
        "--mode", choices=["sitemap", "crawl", "both"], default="sitemap"
    )
    p_discover.add_argument("--max-urls", dest="max_urls", type=int, default=100)
    p_discover.add_argument("--language")
    p_discover.add_argument("--enriched", action="store_true",
                            help="Parse sitemap XML directly for lastmod/changefreq/priority metadata")
    p_discover.add_argument("--pretty", action="store_true")
    p_discover.set_defaults(func=cmd_discover)

    p_batch = sub.add_parser("fetch-batch", help="Batch fetch URLs from stdin or file (NDJSON output)")
    p_batch.add_argument("--url-file", dest="url_file", default="")
    p_batch.add_argument("--concurrency", type=int, default=3)
    p_batch.add_argument("--timeout", type=int, default=20)
    p_batch.add_argument("--max-tokens", dest="max_tokens", type=int, default=0)
    p_batch.add_argument("--domain-delay", dest="domain_delay", type=float, default=0.0,
                         help="Minimum seconds between requests to the same domain (recommended: 1.0)")
    p_batch.add_argument("--include-tables", action="store_true")
    p_batch.add_argument("--include-links", action="store_true")
    p_batch.add_argument("--pretty", action="store_true")
    p_batch.set_defaults(func=cmd_fetch_batch)

    p_doctor = sub.add_parser("doctor", help="Check all dependencies and services")
    p_doctor.add_argument("--pretty", action="store_true")
    p_doctor.set_defaults(func=cmd_doctor)

    p_setup = sub.add_parser(
        "setup", help="Auto-install deps, start services, configure .env"
    )
    p_setup.add_argument(
        "--tier",
        choices=["core", "all"],
        default="core",
        help="core=fetch/extract/scrape/discover, all=+search+crawl",
    )
    p_setup.add_argument("--pretty", action="store_true")
    p_setup.set_defaults(func=cmd_setup)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command not in ("doctor", "setup"):
        from _deps import ensure_deps

        dep_key = args.command
        if args.command == "scrape" and getattr(args, "use_crawl4ai", False):
            dep_key = "scrape-crawl4ai"
        elif args.command == "fetch-batch":
            dep_key = "fetch"
        ensure_deps(dep_key)

        if args.command == "search" and getattr(args, "fetch_top", 0) > 0:
            ensure_deps("fetch")

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        emit_error(args.command, str(exc), pretty=getattr(args, "pretty", False))
        sys.exit(1)


if __name__ == "__main__":
    main()
