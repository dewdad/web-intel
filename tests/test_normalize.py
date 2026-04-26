import sys
import json
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _normalize import WebResult, SearchResult, DiscoverResult, Timer, emit, emit_error


def test_webresult_to_dict_omits_empty_strings():
    r = WebResult(url="https://example.com", title="", markdown="Hello")
    d = r.to_dict()
    assert "title" not in d
    assert d["markdown"] == "Hello"


def test_webresult_to_dict_preserves_status_and_command():
    r = WebResult(status="ok", command="")
    d = r.to_dict()
    assert d["status"] == "ok"
    assert d["command"] == ""


def test_webresult_to_dict_never_emits_html():
    r = WebResult(url="https://example.com", html="<html><body>raw</body></html>", markdown="content")
    d = r.to_dict()
    assert "html" not in d


def test_webresult_to_dict_emits_truncated_when_true():
    r = WebResult(truncated=True, char_count=5000)
    d = r.to_dict()
    assert d["truncated"] is True
    assert d["char_count"] == 5000


def test_webresult_to_dict_omits_truncated_when_false():
    r = WebResult(truncated=False)
    d = r.to_dict()
    assert d.get("truncated") is False or "truncated" not in d


def test_webresult_to_dict_omits_changed_when_none():
    r = WebResult(changed=None)
    d = r.to_dict()
    assert "changed" not in d


def test_webresult_to_dict_includes_changed_when_set():
    r = WebResult(changed=True, current_hash="sha256:abc", previous_hash="sha256:def")
    d = r.to_dict()
    assert d["changed"] is True


def test_searchresult_to_dict_omits_error_when_not_set():
    r = SearchResult(query="test", results=[])
    d = r.to_dict()
    assert "error" not in d


def test_searchresult_to_dict_includes_error_when_set():
    r = SearchResult(query="test", status="failed", error="oops")
    d = r.to_dict()
    assert d["error"] == "oops"


def test_timer_measures_elapsed():
    import time
    with Timer() as t:
        time.sleep(0.05)
    assert t.elapsed_ms >= 40


def test_emit_error_writes_valid_json(capsys):
    emit_error("test-cmd", "something went wrong", pretty=False)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "failed"
    assert data["command"] == "test-cmd"
    assert data["error"] == "something went wrong"


def test_searchresult_backend_field_preserved():
    r = SearchResult(query="test", backend="ddgs")
    d = r.to_dict()
    assert d["backend"] == "ddgs"


def test_searchresult_backend_defaults_to_empty():
    r = SearchResult(query="test")
    d = r.to_dict()
    # empty string should be omitted per to_dict convention
    assert "backend" not in d or d.get("backend") == ""


import json as _json

def test_emit_json_array_writes_valid_array(capsys):
    from _normalize import emit_json_array
    data = [{"status": "ok", "url": "https://a.com"}, {"status": "ok", "url": "https://b.com"}]
    emit_json_array(data, pretty=False)
    captured = capsys.readouterr()
    parsed = _json.loads(captured.out)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["url"] == "https://a.com"
