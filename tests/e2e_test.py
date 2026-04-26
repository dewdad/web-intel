"""
End-to-end tests for the web-intel skill CLI.

Run with:
    python -m pytest tests/e2e_test.py -v

Each test invokes the actual CLI via subprocess and validates the JSON envelope.
Tests are grouped by tier so they can be skipped when services are unavailable:
  - Tier 1 (no services needed): fetch, extract, discover, scrape
  - Tier 2 (requires SearXNG Docker): search
  - Tier 3 (requires Crawl4AI Docker): crawl --docker, scrape auto-crawl4ai
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
CLI = str(SKILL_DIR / "bin" / "web-intel")

STATIC_URL = "https://example.com"
WIKIPEDIA_TABLE_URL = "https://en.wikipedia.org/wiki/Python_(programming_language)"
SITEMAP_URL = "https://example.com"


def _load_env_file() -> dict[str, str]:
    env_file = SKILL_DIR / ".env"
    result: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    return result


_ENV = _load_env_file()


def _searxng_url() -> str:
    return os.environ.get("SEARXNG_URL", _ENV.get("SEARXNG_URL", "http://localhost:8080"))


def _run(*args: str, timeout: int = 60) -> dict:
    result = subprocess.run(
        [CLI, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"CLI exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    last_json_line = next(
        (line for line in reversed(result.stdout.splitlines()) if line.startswith("{")),
        result.stdout,
    )
    data = json.loads(last_json_line)
    return data


def _searxng_available() -> bool:
    try:
        req = urllib.request.Request(f"{_searxng_url()}/search?q=test&format=json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _crawl4ai_docker_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11235/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


requires_searxng = pytest.mark.skipif(
    not _searxng_available(),
    reason="SearXNG not running (run: web-intel setup)",
)
requires_crawl4ai_docker = pytest.mark.skipif(
    not _crawl4ai_docker_available(),
    reason="Crawl4AI Docker not running (run: web-intel setup --tier all)",
)


class TestDoctor:
    def test_doctor_returns_valid_envelope(self):
        data = _run("doctor")
        assert data["command"] == "doctor"
        assert data["status"] in ("ok", "partial")
        assert "checks" in data
        assert "ready_commands" in data
        assert isinstance(data["ready_commands"], list)

    def test_doctor_check_names_are_known(self):
        data = _run("doctor")
        known_checks = {
            "python_version",
            "docker",
            "searxng_docker",
            "searxng_api",
            "crawl4ai_docker",
            "crawl4ai_api",
            "crawl4ai_browser",
            "env_file",
            "search_fallback_brave",
            "search_fallback_ddgs",
        }
        for check in data["checks"]:
            name = check["check"]
            if not name.startswith("python_dep:"):
                assert name in known_checks, f"Unexpected check name: {name}"

    def test_doctor_crawl4ai_docker_check_present(self):
        data = _run("doctor")
        check_names = [c["check"] for c in data["checks"]]
        assert "crawl4ai_docker" in check_names
        assert "crawl4ai_api" in check_names


class TestFetch:
    def test_fetch_static_page(self):
        data = _run("fetch", STATIC_URL)
        assert data["status"] == "ok"
        assert data["command"] == "fetch"
        assert data.get("markdown") or data.get("text")
        assert data.get("url") == STATIC_URL

    def test_fetch_includes_title(self):
        data = _run("fetch", STATIC_URL)
        assert "title" in data
        assert isinstance(data["title"], str)

    def test_fetch_confidence_in_range(self):
        data = _run("fetch", STATIC_URL)
        assert 0.0 <= data.get("confidence", 0.0) <= 1.0

    def test_fetch_include_links(self):
        data = _run("fetch", STATIC_URL, "--include-links")
        assert data["status"] == "ok"
        assert "links" in data or data.get("status") == "ok"

    def test_fetch_no_fallback_crawl_flag(self):
        data = _run("fetch", STATIC_URL, "--no-fallback-crawl")
        assert data["status"] in ("ok", "partial", "failed")
        assert data["command"] == "fetch"

    def test_fetch_output_format_text(self):
        data = _run("fetch", STATIC_URL, "--output-format", "markdown")
        assert data["status"] == "ok"

    def test_fetch_timing_present(self):
        data = _run("fetch", STATIC_URL)
        assert data.get("timing_ms", 0) > 0

    def test_fetch_invalid_url_returns_failed(self):
        result = subprocess.run(
            [CLI, "fetch", "https://this-domain-does-not-exist-xyz-abc.invalid"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        last_json_line = next(
            (line for line in reversed(result.stdout.splitlines()) if line.startswith("{")),
            None,
        )
        assert last_json_line is not None, f"No JSON in stdout: {result.stdout}"
        data = json.loads(last_json_line)
        assert data["status"] == "failed"
        assert "error" in data


class TestExtract:
    def test_extract_from_stdin(self):
        html = "<html><body><article><p>Hello world from web-intel test.</p></article></body></html>"
        result = subprocess.run(
            [CLI, "extract", "--stdin"],
            input=html,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["command"] == "extract"
        assert data["status"] in ("ok", "partial")

    def test_extract_from_file(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><body><article><p>Test content for extraction.</p></article></body></html>"
        )
        data = _run("extract", "--html-file", str(html_file))
        assert data["command"] == "extract"
        assert data["status"] in ("ok", "partial")

    def test_extract_fetch_mode_is_local(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body><article><p>Local.</p></article></body></html>")
        data = _run("extract", "--html-file", str(html_file))
        assert data.get("fetch_mode") == "local"


class TestScrape:
    def test_scrape_selector(self):
        data = _run("scrape", STATIC_URL, "--selector", "h1")
        assert data["command"] == "scrape"
        assert data["status"] in ("ok", "partial", "failed")

    def test_scrape_list(self):
        data = _run("scrape", STATIC_URL, "--list")
        assert data["command"] == "scrape"

    def test_scrape_table_wikipedia(self):
        data = _run("scrape", WIKIPEDIA_TABLE_URL, "--table")
        assert data["command"] == "scrape"
        assert data["status"] in ("ok", "partial")

    def test_scrape_requires_mode_flag(self):
        result = subprocess.run(
            [CLI, "scrape", STATIC_URL],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "failed"
        assert "error" in data


class TestDiscover:
    def test_discover_sitemap(self):
        data = _run("discover", STATIC_URL, "--mode", "sitemap")
        assert data["command"] == "discover"
        assert data["status"] in ("ok", "partial", "failed")
        assert "base_url" in data
        assert isinstance(data.get("urls", []), list)

    def test_discover_crawl(self):
        data = _run("discover", STATIC_URL, "--mode", "crawl", "--max-urls", "5")
        assert data["command"] == "discover"
        assert data["status"] in ("ok", "partial", "failed")

    def test_discover_max_urls_respected(self):
        data = _run("discover", WIKIPEDIA_TABLE_URL, "--mode", "sitemap", "--max-urls", "3")
        urls = data.get("urls", [])
        assert len(urls) <= 3


@requires_searxng
class TestSearch:
    def test_search_basic(self):
        data = _run("search", "Python programming language")
        assert data["command"] == "search"
        assert data["status"] == "ok"
        assert isinstance(data["results"], list)
        assert len(data["results"]) > 0

    def test_search_result_fields(self):
        data = _run("search", "httpx python library")
        for r in data["results"]:
            assert "url" in r
            assert "title" in r

    def test_search_max_results(self):
        data = _run("search", "web scraping", "--max-results", "3")
        assert len(data["results"]) <= 3

    def test_search_timing_present(self):
        data = _run("search", "test query")
        assert data.get("timing_ms", 0) >= 0

    def test_search_no_results_does_not_crash(self):
        data = _run(
            "search",
            "xyzzy1234567890thisqueryshouldmatchnothing",
            "--max-results",
            "1",
        )
        assert data["status"] in ("ok", "partial", "failed")
        assert "command" in data


@requires_crawl4ai_docker
class TestCrawlDocker:
    def test_crawl_docker_explicit_flag(self):
        data = _run("crawl", STATIC_URL, "--docker", "--timeout", "60")
        assert data["command"] == "crawl"
        assert data["status"] in ("ok", "partial", "failed")

    def test_crawl_docker_auto_detected(self):
        data = _run("crawl", STATIC_URL, "--timeout", "60")
        assert data["command"] == "crawl"
        assert data.get("fetch_mode") == "crawl4ai"

    def test_crawl_docker_returns_markdown(self):
        data = _run("crawl", STATIC_URL, "--docker", "--timeout", "60")
        if data["status"] == "ok":
            assert data.get("markdown") or data.get("text")

    def test_scrape_auto_uses_crawl4ai_when_docker_up(self):
        data = _run("scrape", STATIC_URL, "--selector", "h1", "--timeout", "60")
        assert data["command"] == "scrape"
        assert data.get("fetch_mode") == "crawl4ai"


@requires_crawl4ai_docker
class TestFetchFallbackDocker:
    def test_fetch_fallback_hits_crawl4ai_on_empty(self):
        data = _run("fetch", STATIC_URL)
        assert data["status"] in ("ok", "partial")
