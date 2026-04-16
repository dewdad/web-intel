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
    )
    emit(result.to_dict(), pretty=args.pretty)


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

    if (
        args.fallback_crawl
        and result.status in ("failed", "partial")
        and "JavaScript" in (result.error or "")
    ):
        try:
            from _crawl4ai_crawl import crawl

            crawl_result = crawl(args.url, timeout=args.timeout)
            if crawl_result.status == "ok" and crawl_result.markdown:
                result = crawl_result
                result.command = "fetch"
        except ImportError:
            pass

    result.command = "fetch"
    emit(result.to_dict(), pretty=args.pretty)


def cmd_crawl(args: argparse.Namespace) -> None:
    from _crawl4ai_crawl import crawl

    result = crawl(
        args.url,
        wait_for=args.wait_for,
        screenshot=args.screenshot,
        pdf=args.pdf,
        execute_js=args.execute_js,
        timeout=args.timeout,
        headless=args.headless,
        use_docker=args.docker,
    )
    result.command = "crawl"
    emit(result.to_dict(), pretty=args.pretty)


def cmd_scrape(args: argparse.Namespace) -> None:
    from _httpx_fetch import fetch
    from _bs4_scrape import scrape_selector, scrape_tables, scrape_lists

    if args.use_crawl4ai:
        from _crawl4ai_crawl import get_raw_html

        html = get_raw_html(
            args.url,
            wait_for=getattr(args, "wait_for", None),
            timeout=getattr(args, "timeout", 60),
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

    if args.table:
        result = scrape_tables(html, url=args.url)
    elif args.list:
        result = scrape_lists(html, url=args.url)
    elif args.selector:
        result = scrape_selector(
            html, args.selector, url=args.url, attribute=args.attribute
        )
    else:
        emit_error(
            "scrape", "Provide --selector, --table, or --list", pretty=args.pretty
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
    emit(result.to_dict(), pretty=args.pretty)


def cmd_discover(args: argparse.Namespace) -> None:
    from _trafilatura_extract import discover_sitemap, discover_crawl

    if args.mode in ("sitemap", "both"):
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


def cmd_doctor(args: argparse.Namespace) -> None:
    """Check all dependencies and services. Emits JSON diagnostic."""
    import importlib
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

    # 7. Crawl4AI browser
    crawl4ai_browser_ok = False
    try:
        playwright_path = Path.home() / ".cache" / "ms-playwright"
        if playwright_path.exists() and any(playwright_path.iterdir()):
            crawl4ai_browser_ok = True
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

    # 8. .env file
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
    if searxng_api_ok and core_deps_ok:
        ready_tiers.append("search")
    if crawl4ai_browser_ok and core_deps_ok:
        ready_tiers.append("crawl")

    emit(
        {
            "status": "ok" if all_ok else "partial",
            "command": "doctor",
            "skill_dir": str(_SKILL_DIR),
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

    # 4. Crawl4AI browser setup (only if tier=all)
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
    p_search.add_argument("--pretty", action="store_true")
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
    p_crawl.add_argument("--pretty", action="store_true")
    p_crawl.set_defaults(func=cmd_crawl)

    p_scrape = sub.add_parser("scrape")
    p_scrape.add_argument("url")
    p_scrape.add_argument("--selector")
    p_scrape.add_argument("--attribute")
    p_scrape.add_argument("--table", action="store_true")
    p_scrape.add_argument("--list", action="store_true")
    p_scrape.add_argument("--use-crawl4ai", action="store_true")
    p_scrape.add_argument("--pretty", action="store_true")
    p_scrape.set_defaults(func=cmd_scrape)

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--html-file", dest="html_file")
    p_extract.add_argument("--stdin", action="store_true")
    p_extract.add_argument("--url", default="")
    p_extract.add_argument("--include-tables", action="store_true")
    p_extract.add_argument("--include-links", action="store_true")
    p_extract.add_argument("--output-format", dest="output_format", default="markdown")
    p_extract.add_argument("--pretty", action="store_true")
    p_extract.set_defaults(func=cmd_extract)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("url")
    p_discover.add_argument(
        "--mode", choices=["sitemap", "crawl", "both"], default="sitemap"
    )
    p_discover.add_argument("--max-urls", dest="max_urls", type=int, default=100)
    p_discover.add_argument("--language")
    p_discover.add_argument("--pretty", action="store_true")
    p_discover.set_defaults(func=cmd_discover)

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

        ensure_deps(args.command)

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        emit_error(args.command, str(exc), pretty=getattr(args, "pretty", False))
        sys.exit(1)


if __name__ == "__main__":
    main()
