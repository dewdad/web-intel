import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _deps import _import_name, _missing, _stamp_path


def test_import_name_maps_pip_names():
    assert _import_name("beautifulsoup4") == "bs4"
    assert _import_name("httpx-retries") == "httpx_retries"
    assert _import_name("httpx[http2]") == "httpx"
    assert _import_name("trafilatura") == "trafilatura"
    assert _import_name("ddgs") == "ddgs"


def test_import_name_falls_back_to_pkg_name():
    assert _import_name("somepackage") == "somepackage"
    assert _import_name("somepackage[extra]") == "somepackage"


def test_missing_detects_fake_uninstalled_package():
    missing = _missing(["this_package_definitely_does_not_exist_xyz_123"])
    assert "this_package_definitely_does_not_exist_xyz_123" in missing


def test_stamp_path_is_deterministic():
    path1 = _stamp_path(["httpx", "trafilatura"])
    path2 = _stamp_path(["trafilatura", "httpx"])
    assert path1 == path2


def test_stamp_path_differs_for_different_deps():
    path1 = _stamp_path(["httpx"])
    path2 = _stamp_path(["trafilatura"])
    assert path1 != path2


def test_clear_stamp_cache_callable():
    from _deps import clear_stamp_cache
    clear_stamp_cache()
