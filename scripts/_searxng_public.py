"""Public SearXNG instance support.

Lets users skip Docker entirely by pointing ``SEARXNG_URL`` at a community
instance. We keep a curated, deliberately-short list of instances that
historically expose ``format=json`` and answer reliably; anything that
doesn't is filtered out at probe time.

Why a curated list, not searx.space scraping:
  * The set of instances that actually return JSON (vs just HTML) is small
    and changes slowly. A vendored list is good enough and avoids an extra
    runtime dependency on yet another moving target.
  * Public instances are best-effort. Rate limits, bot blocks, and engine
    captchas are normal. Agents must always have a fallback chain (Brave/
    ddgs) ready, which web-intel already provides.

The probe used here is ``probe_searxng`` from ``_docker``, which already
checks both reachability AND that the response decodes as JSON with at
least a recognisable result shape — so an instance that disabled the JSON
format is correctly rejected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from _config import get_logger

log = get_logger("searxng_public")


# Curated list of community instances known to expose format=json at the
# time of writing. Order is significance-by-uptime, not preference; the
# auto-picker probes them in this order and returns the first that works.
#
# Updating this list is cheap: just edit the constant. There is intentionally
# no auto-refresh — we want users to be able to audit the file diff when
# the default targets change.
PUBLIC_INSTANCES: tuple[str, ...] = (
    "https://searx.be",
    "https://search.inetol.net",
    "https://priv.au",
    "https://search.bus-hit.me",
    "https://baresearch.org",
    "https://searx.tiekoetter.com",
    "https://paulgo.io",
)


@dataclass
class PublicPickResult:
    url: str | None
    tried: list[dict]  # [{"url": ..., "ok": bool, "reason": str, "latency_ms": int}]


def is_public_url(url: str) -> bool:
    """Return True if ``url`` clearly points at a non-loopback host.

    Used to short-circuit Docker discovery: if SEARXNG_URL is already a
    public/remote instance, there is no point poking ``docker inspect``.
    """
    if not url:
        return False
    lower = url.lower()
    # Strip scheme to inspect just the host part — avoids accidentally
    # matching "127" inside a path segment.
    for prefix in ("https://", "http://"):
        if lower.startswith(prefix):
            lower = lower[len(prefix):]
            break
    host = lower.split("/", 1)[0].split(":", 1)[0]
    local_hosts = {"127.0.0.1", "localhost", "0.0.0.0", "[::1]", "::1"}
    return host not in local_hosts and not host.startswith("127.")


def pick_public_instance(
    candidates: tuple[str, ...] = PUBLIC_INSTANCES,
    timeout: int = 6,
    inter_probe_delay: float = 0.4,
) -> PublicPickResult:
    """Probe ``candidates`` in order and return the first that answers JSON.

    Sequential, not parallel — public instances are courtesy infrastructure
    and we don't want to hammer all of them on every setup call. Sequential
    probing also means we stop as soon as we find a working one.

    A small ``inter_probe_delay`` is inserted between probes specifically to
    avoid self-triggering the 429 rate limiters that several public
    instances run with very tight thresholds (a single setup run otherwise
    looks like a 7-request burst from one IP).
    """
    import time

    # Local import: probe_searxng lives in _docker but does not require
    # docker itself; it's just an HTTP probe that validates the JSON shape.
    from _docker import probe_searxng

    tried: list[dict] = []
    for idx, url in enumerate(candidates):
        if idx > 0 and inter_probe_delay > 0:
            time.sleep(inter_probe_delay)
        probe = probe_searxng(url, timeout=timeout, retries=0)
        entry: dict = {
            "url": url,
            "ok": bool(probe.reachable and not probe.engines_degraded),
            "latency_ms": probe.latency_ms,
        }
        if not probe.reachable:
            # Precise reason — surfaces 403 (instance blocks bots), 429
            # (rate-limited), dns_or_connect_fail (instance offline), etc.
            entry["reason"] = probe.error_kind or "unreachable_or_no_json"
            if probe.http_status:
                entry["http_status"] = probe.http_status
        elif probe.engines_degraded:
            entry["reason"] = "engines_degraded"
        tried.append(entry)
        if entry["ok"]:
            log.info("Selected public SearXNG instance: %s (%dms)", url, probe.latency_ms)
            return PublicPickResult(url=url, tried=tried)

    log.warning(
        "No public SearXNG instance answered with JSON results "
        "(tried %d). Will fall back to Brave/ddgs at search time.",
        len(tried),
    )
    return PublicPickResult(url=None, tried=tried)


def write_searxng_url_to_env(env_path: Path, url: str, mode: str = "public") -> None:
    """Update or append SEARXNG_URL (and SEARXNG_MODE) in a .env file.

    Preserves all other lines and comments. If the keys already exist they
    are rewritten in place; otherwise they are appended.
    """
    keys = {"SEARXNG_URL": url, "SEARXNG_MODE": mode}

    if env_path.is_file():
        try:
            text = env_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = env_path.read_text(encoding="latin-1")
        lines = text.splitlines()
    else:
        lines = []

    seen: set[str] = set()
    out_lines: list[str] = []
    for raw in lines:
        stripped = raw.lstrip("\ufeff").lstrip()
        replaced = False
        for key, value in keys.items():
            if stripped.startswith(f"{key}=") or stripped.startswith(f"#{key}="):
                out_lines.append(f"{key}={value}")
                seen.add(key)
                replaced = True
                break
        if not replaced:
            out_lines.append(raw)

    for key, value in keys.items():
        if key not in seen:
            out_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    # Also update the live process so the same setup invocation that wrote
    # the file uses the new value for any subsequent probes.
    for key, value in keys.items():
        os.environ[key] = value
