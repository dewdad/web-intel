#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    from _trafilatura_extract import fetch_and_extract, extract_from_html
    from _crawl4ai_crawl import crawl

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

    # Fallback to Crawl4AI if static fetch returned empty/failed
    if (
        args.fallback_crawl
        and result.status in ("failed", "partial")
        and "JavaScript" in (result.error or "")
    ):
        crawl_result = crawl(args.url, timeout=args.timeout)
        if crawl_result.status == "ok" and crawl_result.markdown:
            result = crawl_result
            result.command = "fetch"

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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

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
