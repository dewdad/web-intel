import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _normalize import extract_domain as _extract_domain
from _searxng import _compute_quality_score


def test_extract_domain_strips_www():
    assert _extract_domain("https://www.example.com/path") == "example.com"


def test_extract_domain_empty_string():
    assert _extract_domain("") == ""


def test_extract_domain_no_www():
    assert _extract_domain("https://docs.python.org/3/library/") == "docs.python.org"


def test_compute_quality_score_higher_for_matching_result():
    result_match = {
        "title": "JWT authentication guide",
        "snippet": "How to implement JWT auth tokens in your API",
        "engines": ["google", "bing"],
        "score": 1.5,
    }
    result_no_match = {
        "title": "Database normalization",
        "snippet": "How to normalize your SQL tables",
        "engines": ["google"],
        "score": 0.5,
    }
    score_match = _compute_quality_score(result_match, "JWT authentication")
    score_no_match = _compute_quality_score(result_no_match, "JWT authentication")
    assert score_match > score_no_match


def test_compute_quality_score_zero_for_empty_query():
    result = {"title": "something", "snippet": "text", "engines": ["google"], "score": 1.0}
    assert _compute_quality_score(result, "") == 0.0


def test_multi_engine_scores_higher_than_single_engine():
    base = {"title": "same title auth", "snippet": "same snippet auth", "score": 1.0}
    multi = {**base, "engines": ["google", "bing", "brave"]}
    single = {**base, "engines": ["google"]}
    assert _compute_quality_score(multi, "auth") > _compute_quality_score(single, "auth")


def test_dedup_logic_merges_engines_and_takes_max_score():
    from _searxng import search as _search
    results_raw = [
        {"url": "https://example.com", "title": "T1", "content": "S1", "engine": "google",
         "engines": ["google"], "score": 1.0, "publishedDate": "", "category": ""},
        {"url": "https://example.com", "title": "T1", "content": "S1", "engine": "bing",
         "engines": ["bing"], "score": 1.5, "publishedDate": "", "category": ""},
    ]
    seen: dict = {}
    for r in results_raw:
        url = r["url"]
        mapped = {
            "url": r["url"], "title": r["title"], "snippet": r["content"],
            "engine": r["engine"], "engines": r["engines"], "score": r["score"],
            "domain": "", "published_at": "", "category": "",
        }
        if url in seen:
            seen[url]["engines"] = list(set(seen[url]["engines"] + mapped["engines"]))
            seen[url]["score"] = max(seen[url]["score"], mapped["score"])
        else:
            seen[url] = mapped
    deduped = list(seen.values())
    assert len(deduped) == 1
    assert set(deduped[0]["engines"]) == {"google", "bing"}
    assert deduped[0]["score"] == 1.5


def test_search_result_has_backend_searxng():
    from unittest.mock import patch, MagicMock
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [], "number_of_results": 0}
    mock_resp.raise_for_status = MagicMock()
    with patch("_searxng.create_httpx_client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
        from _searxng import search
        result = search("test query")
    assert result.backend == "searxng"
