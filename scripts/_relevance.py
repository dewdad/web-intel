from __future__ import annotations

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b[a-z]{2,}\b', text.lower())


def _tfidf_score(query_tokens: list[str], para_tokens: list[str],
                 doc_freqs: dict[str, int], num_docs: int) -> float:
    if not para_tokens or not query_tokens:
        return 0.0
    para_counts = Counter(para_tokens)
    score = 0.0
    for token in set(query_tokens):
        tf = para_counts.get(token, 0) / len(para_tokens)
        df = doc_freqs.get(token, 0)
        idf = math.log((num_docs + 1) / (df + 1)) + 1
        score += tf * idf
    return score


def filter_relevant_paragraphs(
    markdown: str,
    query: str,
    *,
    top_n: int = 10,
    min_chars: int = 80,
) -> str:
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', markdown) if len(p.strip()) >= min_chars]
    if not paragraphs:
        return markdown

    query_tokens = _tokenize(query)
    tokenized_paras = [_tokenize(p) for p in paragraphs]

    doc_freqs: dict[str, int] = Counter()
    for tokens in tokenized_paras:
        for token in set(tokens):
            doc_freqs[token] += 1

    scores = [
        _tfidf_score(query_tokens, tokens, doc_freqs, len(paragraphs))
        for tokens in tokenized_paras
    ]

    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    selected = sorted([i for i, _ in indexed[:top_n]])
    return "\n\n".join(paragraphs[i] for i in selected)


# Heuristic patterns for noise blocks (nav, footer, cookie banners)
_NOISE_PATTERNS = re.compile(
    r'\b(cookie|privacy policy|terms of service|all rights reserved|sitemap|'
    r'subscribe|newsletter|follow us|share this|back to top|skip to|'
    r'copyright ©|©\s*\d{4})\b',
    re.IGNORECASE,
)
_MIN_CONTENT_WORDS = 8  # blocks shorter than this with noise signals are pruned


def _bm25_score(
    query_tokens: list[str],
    para_tokens: list[str],
    doc_freqs: dict[str, int],
    num_docs: int,
    k1: float = 1.5,
    b: float = 0.75,
    avg_dl: float = 50.0,
) -> float:
    """BM25 relevance score for a paragraph against a query."""
    if not para_tokens or not query_tokens:
        return 0.0
    dl = len(para_tokens)
    para_counts = Counter(para_tokens)
    score = 0.0
    for token in set(query_tokens):
        tf = para_counts.get(token, 0)
        if tf == 0:
            continue
        df = doc_freqs.get(token, 0)
        idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1)
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
        score += idf * tf_norm
    return score


def _is_noise_block(para: str) -> bool:
    """Return True if a paragraph looks like nav/footer/boilerplate."""
    words = _tokenize(para)
    if len(words) < _MIN_CONTENT_WORDS:
        return bool(_NOISE_PATTERNS.search(para))
    noise_word_count = sum(len(_tokenize(m)) for m in _NOISE_PATTERNS.findall(para))
    return noise_word_count / max(len(words), 1) > 0.3


def fit_markdown(markdown: str, *, query: str = "", min_chars: int = 40) -> str:
    """
    Remove boilerplate/noise blocks from markdown.

    If `query` is provided, also ranks remaining paragraphs by BM25 relevance
    and returns only the top 60% (minimum 3 paragraphs), preserving order.

    Noise removal is always applied regardless of query.
    Code blocks (``` fenced) are always preserved.
    """
    if not markdown:
        return markdown

    # Split into paragraphs, preserving fenced code blocks as atomic units
    raw_paras = re.split(r'\n{2,}', markdown)

    kept: list[str] = []
    in_code = False
    code_buf: list[str] = []

    for para in raw_paras:
        stripped = para.strip()
        if not stripped:
            continue

        # Fenced code block handling (always keep)
        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                code_buf = [stripped]
                if stripped.count("```") >= 2:  # single-line fence
                    kept.append(stripped)
                    in_code = False
                    code_buf = []
            else:
                code_buf.append(stripped)
                kept.append("\n\n".join(code_buf))
                in_code = False
                code_buf = []
            continue

        if in_code:
            code_buf.append(stripped)
            continue

        if len(stripped) < min_chars:
            continue

        if _is_noise_block(stripped):
            continue

        kept.append(stripped)

    if not kept:
        # Fell through — return original to avoid data loss
        return markdown

    if not query:
        return "\n\n".join(kept)

    # BM25 re-ranking with query
    query_tokens = _tokenize(query)
    tokenized = [_tokenize(p) for p in kept]
    avg_dl = sum(len(t) for t in tokenized) / max(len(tokenized), 1)

    doc_freqs: dict[str, int] = Counter()
    for tokens in tokenized:
        for token in set(tokens):
            doc_freqs[token] += 1

    scores = [
        _bm25_score(query_tokens, tokens, doc_freqs, len(kept), avg_dl=avg_dl)
        for tokens in tokenized
    ]

    # Keep top 60% by BM25, minimum 3 paragraphs, preserving original order
    top_n = max(3, int(len(kept) * 0.6))
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    selected = sorted(i for i, _ in indexed[:top_n])
    return "\n\n".join(kept[i] for i in selected)
