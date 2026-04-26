import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _page_cache as page_cache_module


def _make_temp_cache(tmp_path: Path):
    cache_file = tmp_path / "page_cache.json"
    page_cache_module._CACHE_FILE = cache_file
    return cache_file


def test_first_call_returns_changed_none(tmp_path):
    _make_temp_cache(tmp_path)
    changed, prev, curr = page_cache_module.check_and_update("https://example.com", "content")
    assert changed is None


def test_second_call_with_same_content_returns_false(tmp_path):
    _make_temp_cache(tmp_path)
    page_cache_module.check_and_update("https://example.com", "same content")
    changed, prev, curr = page_cache_module.check_and_update("https://example.com", "same content")
    assert changed is False


def test_second_call_with_different_content_returns_true(tmp_path):
    _make_temp_cache(tmp_path)
    page_cache_module.check_and_update("https://example.com", "original content")
    changed, prev, curr = page_cache_module.check_and_update("https://example.com", "changed content")
    assert changed is True


def test_current_hash_starts_with_sha256():
    _, _, curr = page_cache_module.check_and_update.__wrapped__("https://x.com", "data") if hasattr(page_cache_module.check_and_update, "__wrapped__") else (None, None, None)
    changed, prev, curr = page_cache_module.check_and_update("https://example.com/hash-test", "data")
    assert curr.startswith("sha256:")


def test_cache_file_created(tmp_path):
    cache_file = _make_temp_cache(tmp_path)
    page_cache_module.check_and_update("https://example.com/file-test", "data")
    assert cache_file.exists()
