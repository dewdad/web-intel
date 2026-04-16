from __future__ import annotations

from typing import Optional

from _config import create_httpx_client, get_logger
from _normalize import WebResult, Timer

log = get_logger("httpx_fetch")


def fetch(
    url: str,
    *,
    timeout: Optional[int] = None,
    include_headers: bool = False,
) -> tuple[str, int, dict[str, str]]:
    """Fetch URL content via httpx. Returns (html_body, status_code, response_headers)."""
    with create_httpx_client(timeout=timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()
        headers = dict(resp.headers) if include_headers else {}
        return resp.text, resp.status_code, headers


def fetch_to_result(
    url: str,
    *,
    timeout: Optional[int] = None,
) -> WebResult:
    """Fetch URL and return a WebResult with raw HTML in the text field."""
    with Timer() as t:
        try:
            html, status_code, _ = fetch(url, timeout=timeout)
        except Exception as exc:
            log.error("Fetch failed for %s: %s", url, exc)
            return WebResult(
                url=url,
                status="failed",
                fetch_mode="httpx",
                error=f"httpx fetch failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    return WebResult(
        url=url,
        text=html,
        fetch_mode="httpx",
        source_engine="httpx",
        timing_ms=t.elapsed_ms,
    )
