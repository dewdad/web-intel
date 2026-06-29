"""Shared configuration, httpx client factory, and logging for web-intel."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional


def _load_dotenv(env_path: Optional[Path] = None) -> None:
    """Load .env file into os.environ. No-op if file missing.

    Robust to:
    - UTF-8 BOM (``\ufeff``) at start of file (Windows editors often add this).
    - CRLF line endings (``str.strip()`` already handles ``\r``).
    - Mixed/legacy encodings — falls back to latin-1 so we never crash on a
      stray non-ASCII byte in a comment.
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    try:
        # utf-8-sig transparently strips a leading BOM if present.
        text = env_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = env_path.read_text(encoding="latin-1")
    for line in text.splitlines():
        # Belt-and-suspenders: strip any stray BOM that appeared mid-stream
        # (multiple concatenated .env files, copy-paste artefacts, etc.).
        line = line.lstrip("\ufeff").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:  # don't override existing
            os.environ[key] = value


_load_dotenv()

SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://127.0.0.1:9871")
SEARXNG_API_KEY: Optional[str] = os.environ.get("SEARXNG_API_KEY")

# How web-intel resolves the SearXNG backend.
#   "auto"     — probe SEARXNG_URL; if it answers, use it. Otherwise try to
#                discover a Docker container named ``wrs-searxng``. Default.
#   "public"   — treat SEARXNG_URL as a remote/public instance. Skip Docker
#                discovery entirely. Doctor stops nagging about Docker.
#   "docker"   — only use the local Docker container (current behaviour).
#   "disabled" — never use SearXNG; go straight to Brave/ddgs fallback.
SEARXNG_MODE: str = os.environ.get("SEARXNG_MODE", "auto").lower()

CRAWL4AI_DOCKER_URL: str = os.environ.get(
    "CRAWL4AI_DOCKER_URL", "http://localhost:11235"
)
CRAWL4AI_API_KEY: Optional[str] = os.environ.get("CRAWL4AI_API_KEY")

HTTP_TIMEOUT: int = int(os.environ.get("HTTP_TIMEOUT", "30"))
MAX_CONCURRENT_FETCHES: int = int(os.environ.get("MAX_CONCURRENT_FETCHES", "5"))

USER_AGENT: str = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; web-intel/0.1; +https://github.com/dewdad/web-intel)",
)

# stderr-only logging keeps stdout clean for JSON output
LOG_LEVEL: str = os.environ.get("WRS_LOG_LEVEL", "WARNING").upper()


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to stderr only."""
    logger = logging.getLogger(f"wrs.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.WARNING))
    return logger


def create_httpx_client(
    *,
    timeout: Optional[int] = None,
    max_connections: int = 100,
    max_keepalive: int = 20,
    retries: int = 3,
    http2: bool = True,
) -> "httpx.Client":
    """Create a configured httpx.Client with retry transport.

    Caller is responsible for closing the client (use as context manager).
    """
    import httpx

    timeout_val = timeout or HTTP_TIMEOUT

    try:
        from httpx_retries import RetryTransport, ExponentialBackoff

        transport = RetryTransport(
            wrapped_transport=httpx.HTTPTransport(
                http2=http2,
                limits=httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive,
                ),
            ),
            retry_strategy=ExponentialBackoff(max_retries=retries),
        )
    except ImportError:
        transport = httpx.HTTPTransport(
            http2=http2,
            retries=retries,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
            ),
        )

    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout_val),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def create_async_httpx_client(
    *,
    timeout: Optional[int] = None,
    max_connections: int = 100,
    max_keepalive: int = 20,
    retries: int = 3,
    http2: bool = True,
) -> "httpx.AsyncClient":
    """Create a configured httpx.AsyncClient with retry transport.

    Caller is responsible for closing the client (use as async context manager).
    """
    import httpx

    timeout_val = timeout or HTTP_TIMEOUT

    try:
        from httpx_retries import AsyncRetryTransport, ExponentialBackoff

        transport = AsyncRetryTransport(
            wrapped_transport=httpx.AsyncHTTPTransport(
                http2=http2,
                limits=httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive,
                ),
            ),
            retry_strategy=ExponentialBackoff(max_retries=retries),
        )
    except ImportError:
        transport = httpx.AsyncHTTPTransport(
            http2=http2,
            retries=retries,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
            ),
        )

    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout_val),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
