from __future__ import annotations

import asyncio
from typing import Any, Optional

from _config import CRAWL4AI_DOCKER_URL, CRAWL4AI_API_KEY, get_logger
from _normalize import WebResult, Timer

log = get_logger("crawl4ai")


async def _crawl_local(
    url: str,
    *,
    wait_for: Optional[str] = None,
    screenshot: bool = False,
    pdf: bool = False,
    execute_js: Optional[str] = None,
    timeout: int = 60,
    headless: bool = True,
) -> WebResult:
    with Timer() as t:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

            browser_config = BrowserConfig(
                headless=headless,
                browser_type="chromium",
            )

            run_config_kwargs: dict[str, Any] = {}
            if wait_for:
                run_config_kwargs["wait_for"] = f"css:{wait_for}"
            if execute_js:
                run_config_kwargs["js_code"] = [execute_js]
            if screenshot:
                run_config_kwargs["screenshot"] = True
            if pdf:
                run_config_kwargs["pdf"] = True
            run_config_kwargs["page_timeout"] = timeout * 1000

            run_config = CrawlerRunConfig(**run_config_kwargs)

            crawler = AsyncWebCrawler(config=browser_config)
            await crawler.start()
            try:
                result = await crawler.arun(url=url, config=run_config)
            finally:
                await crawler.close()

        except ImportError:
            return WebResult(
                url=url,
                status="failed",
                fetch_mode="crawl4ai",
                error="crawl4ai is not installed. Run: pip install crawl4ai && crawl4ai-setup",
                timing_ms=t.elapsed_ms,
            )
        except Exception as exc:
            log.error("Crawl4AI local crawl failed for %s: %s", url, exc)
            return WebResult(
                url=url,
                status="failed",
                fetch_mode="crawl4ai",
                error=f"Crawl4AI crawl failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    if not result.success:
        return WebResult(
            url=url,
            status="failed",
            fetch_mode="crawl4ai",
            error=f"Crawl4AI reported failure: {result.error_message or 'unknown'}",
            timing_ms=t.elapsed_ms,
        )

    return WebResult(
        url=url,
        canonical_url=getattr(result, "url", url),
        title=getattr(result, "title", "") or "",
        markdown=result.markdown or "",
        text=getattr(result, "extracted_content", "") or result.markdown or "",
        links=[
            {"url": l.get("href", ""), "text": l.get("text", "")}
            for l in (
                getattr(result, "links", {}).get("internal", [])
                + getattr(result, "links", {}).get("external", [])
            )
        ]
        if hasattr(result, "links") and isinstance(getattr(result, "links", None), dict)
        else [],
        images=[
            {"url": img.get("src", ""), "alt": img.get("alt", "")}
            for img in (getattr(result, "media", {}).get("images", []))
        ]
        if hasattr(result, "media") and isinstance(getattr(result, "media", None), dict)
        else [],
        fetch_mode="crawl4ai",
        extract_mode="crawl4ai_markdown",
        source_engine="crawl4ai",
        confidence=0.8 if result.markdown else 0.3,
        timing_ms=t.elapsed_ms,
    )


async def _crawl_docker(
    url: str,
    *,
    wait_for: Optional[str] = None,
    screenshot: bool = False,
    execute_js: Optional[str] = None,
    timeout: int = 60,
) -> WebResult:
    """Crawl via the Crawl4AI Docker server REST API."""
    import httpx

    with Timer() as t:
        try:
            # crawler_config params — build only non-default values
            crawler_params: dict[str, Any] = {
                "stream": False,
                "cache_mode": "bypass",
                "page_timeout": timeout * 1000,
            }
            if wait_for:
                crawler_params["wait_for"] = f"css:{wait_for}"
            if execute_js:
                crawler_params["js_code"] = [execute_js]
            if screenshot:
                crawler_params["screenshot"] = True

            # Schema: CrawlRequestWithHooks — urls must be a list; configs use
            # {"type": "ClassName", "params": {...}} wrapper (crawl4ai deploy/docker/schemas.py)
            payload: dict[str, Any] = {
                "urls": [url],
                "browser_config": {
                    "type": "BrowserConfig",
                    "params": {"headless": True},
                },
                "crawler_config": {
                    "type": "CrawlerRunConfig",
                    "params": crawler_params,
                },
            }

            headers: dict[str, str] = {"Content-Type": "application/json"}
            if CRAWL4AI_API_KEY:
                headers["Authorization"] = f"Bearer {CRAWL4AI_API_KEY}"

            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 30)) as client:
                resp = await client.post(
                    f"{CRAWL4AI_DOCKER_URL}/crawl",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

        except Exception as exc:
            log.error("Crawl4AI Docker request failed: %s", exc)
            return WebResult(
                url=url,
                status="failed",
                fetch_mode="crawl4ai",
                error=f"Crawl4AI Docker request failed: {exc}. Is the server running at {CRAWL4AI_DOCKER_URL}?",
                timing_ms=t.elapsed_ms,
            )

    # Response shape: {"success": true, "results": [CrawlResult, ...]}
    # CrawlResult.markdown is a MarkdownGenerationResult object, not a plain string.
    results_list = data.get("results", [])
    if not results_list:
        return WebResult(
            url=url,
            status="failed",
            fetch_mode="crawl4ai",
            error="Crawl4AI Docker returned empty results list",
            timing_ms=t.elapsed_ms,
        )

    result_data = results_list[0]
    if not result_data.get("success"):
        return WebResult(
            url=url,
            status="failed",
            fetch_mode="crawl4ai",
            error=f"Crawl4AI Docker reported failure: {result_data.get('error_message', 'unknown')}",
            timing_ms=t.elapsed_ms,
        )

    # markdown field is a nested object: {raw_markdown, fit_markdown, ...}
    markdown_obj = result_data.get("markdown") or {}
    if isinstance(markdown_obj, dict):
        markdown = (
            markdown_obj.get("fit_markdown")
            or markdown_obj.get("markdown_with_citations")
            or markdown_obj.get("raw_markdown")
            or ""
        )
    else:
        # older server versions may return a plain string
        markdown = str(markdown_obj)

    links_raw = result_data.get("links") or {}
    links = [
        {"url": l.get("href", ""), "text": l.get("text", "")}
        for l in (links_raw.get("internal", []) + links_raw.get("external", []))
        if isinstance(l, dict)
    ]

    images_raw = (result_data.get("media") or {}).get("images", [])
    images = [
        {"url": img.get("src", ""), "alt": img.get("alt", "")}
        for img in images_raw
        if isinstance(img, dict)
    ]

    return WebResult(
        url=url,
        canonical_url=result_data.get("url", url),
        title=(result_data.get("metadata") or {}).get("title", ""),
        markdown=markdown,
        text=result_data.get("extracted_content", "") or markdown,
        links=links,
        images=images,
        fetch_mode="crawl4ai",
        extract_mode="crawl4ai_markdown",
        source_engine="crawl4ai",
        confidence=0.8 if markdown else 0.3,
        timing_ms=t.elapsed_ms,
    )


def crawl(
    url: str,
    *,
    wait_for: Optional[str] = None,
    screenshot: bool = False,
    pdf: bool = False,
    execute_js: Optional[str] = None,
    timeout: int = 60,
    headless: bool = True,
    use_docker: bool = False,
) -> WebResult:
    """Crawl a URL using Crawl4AI (local browser or Docker server)."""
    if use_docker:
        return asyncio.run(
            _crawl_docker(
                url,
                wait_for=wait_for,
                screenshot=screenshot,
                execute_js=execute_js,
                timeout=timeout,
            )
        )
    return asyncio.run(
        _crawl_local(
            url,
            wait_for=wait_for,
            screenshot=screenshot,
            pdf=pdf,
            execute_js=execute_js,
            timeout=timeout,
            headless=headless,
        )
    )


def get_raw_html(
    url: str,
    *,
    wait_for: Optional[str] = None,
    execute_js: Optional[str] = None,
    timeout: int = 60,
    headless: bool = True,
    use_docker: bool = False,
) -> str:
    """Crawl URL and return raw HTML for downstream BS4 processing."""
    result = crawl(
        url,
        wait_for=wait_for,
        execute_js=execute_js,
        timeout=timeout,
        headless=headless,
        use_docker=use_docker,
    )
    return result.text or result.markdown or ""
