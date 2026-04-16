from __future__ import annotations

import hashlib
import importlib
import subprocess
import sys
from pathlib import Path

_STAMP_DIR = Path(__file__).resolve().parent.parent / ".deps_cache"

# pip package name -> import name (only where they differ)
_IMPORT_MAP: dict[str, str] = {
    "httpx[http2]": "httpx",
    "httpx-retries": "httpx_retries",
    "beautifulsoup4": "bs4",
    "crawl4ai": "crawl4ai",
    "trafilatura": "trafilatura",
    "lxml": "lxml",
}

CORE_DEPS = ["httpx[http2]", "httpx-retries", "trafilatura", "beautifulsoup4", "lxml"]
CRAWL_DEPS = ["crawl4ai"]

_COMMAND_DEPS: dict[str, list[str]] = {
    "search": CORE_DEPS,
    "fetch": CORE_DEPS + CRAWL_DEPS,
    "crawl": CORE_DEPS + CRAWL_DEPS,
    "scrape": CORE_DEPS,
    "extract": ["trafilatura"],
    "discover": ["trafilatura"],
}


def _import_name(pip_pkg: str) -> str:
    return _IMPORT_MAP.get(pip_pkg, pip_pkg.split("[")[0])


def _stamp_path(deps: list[str]) -> Path:
    key = hashlib.md5("|".join(sorted(deps)).encode()).hexdigest()[:12]
    return _STAMP_DIR / f".deps_{key}"


def _is_importable(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def _missing(deps: list[str]) -> list[str]:
    return [pkg for pkg in deps if not _is_importable(_import_name(pkg))]


def _pip_install(packages: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade"] + packages
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def ensure_deps(command: str) -> None:
    """Check and install dependencies required for the given command.

    Uses a stamp file to skip re-checking when deps haven't changed.
    """
    deps = _COMMAND_DEPS.get(command, CORE_DEPS)
    stamp = _stamp_path(deps)

    if stamp.exists():
        return

    missing = _missing(deps)
    if not missing:
        _STAMP_DIR.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        return

    print(
        f"Installing missing dependencies: {', '.join(missing)}",
        file=sys.stderr,
    )
    try:
        _pip_install(missing)
    except subprocess.CalledProcessError as exc:
        print(
            f"Failed to install dependencies: {exc}. "
            f"Run manually: pip install {' '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    still_missing = _missing(deps)
    if still_missing:
        print(
            f"Still missing after install: {', '.join(still_missing)}. "
            f"Run manually: pip install {' '.join(still_missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    _STAMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp.touch()


def clear_stamp_cache() -> None:
    """Remove all stamp files, forcing re-check on next run."""
    if _STAMP_DIR.exists():
        for f in _STAMP_DIR.iterdir():
            f.unlink()
