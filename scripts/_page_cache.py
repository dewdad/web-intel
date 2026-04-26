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


def check_and_update(
    url: str,
    content: str,
    title: str = "",
    *,
    no_cache: bool = False,
) -> tuple[Optional[bool], str, str]:
    if no_cache:
        return None, "", ""
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


def clear_page_cache() -> None:
    try:
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
    except Exception:
        pass
