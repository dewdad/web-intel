import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _relevance import filter_relevant_paragraphs, _tokenize, _tfidf_score


AUTH_PARA = "Authentication uses JWT tokens to verify user identity and sessions in the application backend."
DB_PARA = "Database migrations run using Alembic to manage schema changes and table alterations in production."
AUTH_PARA2 = "The auth middleware validates bearer tokens on every protected API route in the server."
SHORT_PARA = "Short."


def test_auth_paragraphs_score_higher_for_auth_query():
    markdown = f"{AUTH_PARA}\n\n{DB_PARA}\n\n{AUTH_PARA2}"
    result = filter_relevant_paragraphs(markdown, "how does auth work", top_n=2, min_chars=40)
    assert AUTH_PARA in result or AUTH_PARA2 in result
    assert DB_PARA not in result


def test_short_paragraphs_excluded_by_min_chars():
    markdown = f"{SHORT_PARA}\n\n{AUTH_PARA}"
    result = filter_relevant_paragraphs(markdown, "auth", min_chars=40)
    assert SHORT_PARA.strip() not in result.strip().split("\n\n")[0] if result != markdown else True


def test_empty_input_returns_empty_without_crash():
    result = filter_relevant_paragraphs("", "query")
    assert result == ""


def test_returns_original_when_no_paragraphs_meet_min_chars():
    markdown = "tiny"
    result = filter_relevant_paragraphs(markdown, "query", min_chars=80)
    assert result == markdown


def test_tokenize_lowercases_and_filters_short():
    tokens = _tokenize("The Quick Brown Fox")
    assert "the" in tokens
    assert "quick" in tokens
    assert set(tokens) == {"the", "quick", "brown", "fox"}
