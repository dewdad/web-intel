import sys
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "web", Path(__file__).resolve().parent.parent / "scripts" / "web.py"
)
_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_web)

_apply_token_limit = _web._apply_token_limit
_apply_chunking = _web._apply_chunking

from _normalize import WebResult


def test_token_limit_zero_is_noop():
    r = WebResult(markdown="hello world")
    out = _apply_token_limit(r, 0)
    assert out.markdown == "hello world"
    assert not out.truncated


def test_token_limit_sets_char_count():
    r = WebResult(markdown="abc")
    _apply_token_limit(r, 100)
    assert r.char_count == 3


def test_token_limit_truncates_markdown_when_over():
    content = "x" * 1000
    r = WebResult(markdown=content)
    _apply_token_limit(r, 10)
    assert len(r.markdown) < len(content)
    assert r.truncated is True
    assert r.markdown.endswith("[...truncated]")


def test_token_limit_does_not_truncate_when_under():
    r = WebResult(markdown="short text")
    _apply_token_limit(r, 1000)
    assert r.truncated is not True
    assert "truncated" not in r.markdown


def test_token_limit_truncates_text_field_too():
    r = WebResult(text="y" * 500, markdown="y" * 500)
    _apply_token_limit(r, 10)
    assert r.truncated is True
    assert r.text.endswith("[...truncated]")


def test_token_limit_char_count_uses_markdown_preferentially():
    r = WebResult(markdown="abc", text="abcde")
    _apply_token_limit(r, 100)
    assert r.char_count == 3


def test_token_limit_char_count_falls_back_to_text():
    r = WebResult(text="hello")
    _apply_token_limit(r, 100)
    assert r.char_count == 5


def test_chunking_zero_is_noop():
    r = WebResult(markdown="hello world")
    out = _apply_chunking(r, 0, 0)
    assert out.markdown == "hello world"
    assert out.chunk_count == 0


def test_chunking_empty_content_is_noop():
    r = WebResult(markdown="")
    out = _apply_chunking(r, 100, 0)
    assert out.markdown == ""
    assert out.chunk_count == 0


def test_chunking_short_content_is_single_chunk():
    r = WebResult(markdown="hello world")
    _apply_chunking(r, 1000, 0)
    assert r.chunk_count == 1
    assert r.chunk_index == 0
    assert r.markdown == "hello world"


def test_chunking_splits_long_content():
    para = "word " * 100
    content = (para.strip() + "\n\n") * 4
    r = WebResult(markdown=content)
    _apply_chunking(r, 50, 0)
    assert r.chunk_count > 1


def test_chunking_index_selects_correct_chunk():
    para_a = "Alpha " * 60
    para_b = "Beta " * 60
    para_c = "Gamma " * 60
    content = para_a.strip() + "\n\n" + para_b.strip() + "\n\n" + para_c.strip()
    r0 = WebResult(markdown=content)
    r1 = WebResult(markdown=content)
    _apply_chunking(r0, 50, 0)
    _apply_chunking(r1, 50, 1)
    assert r0.markdown != r1.markdown


def test_chunking_index_out_of_bounds_clamps_to_last():
    r = WebResult(markdown="short")
    _apply_chunking(r, 1000, 999)
    assert r.chunk_index == 0


def test_chunking_sets_chunk_tokens():
    r = WebResult(markdown="hello world")
    _apply_chunking(r, 42, 0)
    assert r.chunk_tokens == 42


def test_chunking_also_updates_text_field():
    content = "word " * 200
    r = WebResult(markdown=content, text=content)
    _apply_chunking(r, 50, 0)
    assert len(r.text) < len(content)
    assert r.text == r.markdown


from _relevance import fit_markdown


def test_fit_markdown_called_on_fetch_top_content():
    """fit_markdown removes boilerplate from content markdown."""
    noise = "Cookie policy. Privacy. All rights reserved. Subscribe to newsletter."
    article = "The attention mechanism in transformers computes weighted sums over value vectors using softmax-normalized dot products."
    raw_md = f"{noise}\n\n{article}"
    result = fit_markdown(raw_md, query="attention mechanism transformers")
    assert article in result
    assert "Cookie policy" not in result
