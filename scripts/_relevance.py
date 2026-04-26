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
