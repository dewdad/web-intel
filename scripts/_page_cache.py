from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_CACHE_FILE = Path(__file__).resolve().parent.parent / ".deps_cache" / "page_cache.json"


def _load() -> dict:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save(cache: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def _entry_age_seconds(entry: dict) -> Optional[float]:
    """Return age of a cache entry in seconds, or None if unparseable."""
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return None
    try:
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except (ValueError, TypeError):
        return None


def check_and_update(
    url: str,
    content: str,
    title: str = "",
    *,
    no_cache: bool = False,
    ttl_seconds: int = 0,
) -> tuple[Optional[bool], str, str]:
    """Hash content, compare to last seen, persist new value.

    Args:
        url: Cache key (the page URL).
        content: Body to hash (markdown or text).
        title: Optional title stored alongside the hash for human readability.
        no_cache: Skip both reads and writes — short-circuits to a stateless
            response.
        ttl_seconds: When > 0, treat any cache entry older than this as
            absent. ``previous_hash`` will come back empty and ``changed``
            will be ``None`` (matching first-visit semantics), forcing
            downstream consumers to treat the fetch as fresh.

    Returns ``(changed, previous_hash, current_hash)``:
        - ``changed`` is ``None`` for first visits / TTL-expired entries.
        - ``current_hash`` is always set when ``no_cache`` is False.
    """
    if no_cache:
        return None, "", ""
    current_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]
    cache = _load()
    entry = cache.get(url)

    # TTL handling: an entry past its TTL is logically a cache miss for the
    # purpose of change-detection, but we still overwrite it so the next
    # call within the new window can compare against fresh content.
    if entry and ttl_seconds > 0:
        age = _entry_age_seconds(entry)
        if age is not None and age > ttl_seconds:
            entry = None

    previous_hash = entry["hash"] if entry else ""
    changed: Optional[bool] = None if not entry else (current_hash != previous_hash)
    cache[url] = {
        "hash": current_hash,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
    }
    _save(cache)
    return changed, previous_hash, current_hash


def clear_page_cache() -> None:
    try:
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
    except Exception:
        pass
