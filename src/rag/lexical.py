"""Dependency-free lexical retrieval for serverless deployments.

The primary retriever uses Chroma plus a sentence-transformer model. That stack
(torch + transformers) is far larger than a Vercel Function bundle allows, so
the API switches to this BM25 index when it runs on Vercel. The corpus is only
108 chunks, which makes lexical ranking both fast and accurate for FAQ-style
questions.

The module intentionally imports nothing outside the standard library. It reads
the same ``data/chunks/chunks.jsonl`` file that feeds the Chroma index and
returns hits in the same shape as :class:`src.rag.store.ChromaStore`.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "much",
    "my",
    "of",
    "on",
    "or",
    "should",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class LexicalError(RuntimeError):
    """Raised when the chunk file is missing or malformed."""


def _stem(token: str) -> str:
    """Very small suffix normalizer, enough for English FAQ vocabulary."""

    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, split, drop stopwords, and lightly normalize tokens."""

    return [
        _stem(token)
        for token in _TOKEN_RE.findall(text.casefold())
        if token not in _STOPWORDS
    ]


class LexicalIndex:
    """A small in-memory BM25 index over the chunk corpus."""

    collection_name = "groww_mf_faq_lexical"

    def __init__(
        self,
        chunks_file: str | Path,
        *,
        k1: float = 1.5,
        b: float = 0.75,
        score_scale: float = 2.5,
    ):
        self.chunks_file = Path(chunks_file)
        self.k1 = k1
        self.b = b
        self.score_scale = score_scale
        self._chunks: list[dict[str, Any]] = []
        self._terms: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._document_frequency: Counter[str] = Counter()
        self._average_length = 0.0
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.chunks_file.is_file():
            raise LexicalError(f"Chunks file not found: {self.chunks_file}")

        try:
            lines = self.chunks_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise LexicalError(f"Could not read {self.chunks_file}: {exc}") from exc

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LexicalError(
                    f"Invalid JSON on line {line_number} of {self.chunks_file}"
                ) from exc
            if not isinstance(chunk, dict) or not chunk.get("text"):
                raise LexicalError(
                    f"Chunk on line {line_number} is missing text"
                )

            terms = Counter(tokenize(str(chunk["text"])))
            self._chunks.append(chunk)
            self._terms.append(terms)
            self._lengths.append(sum(terms.values()))
            self._document_frequency.update(terms.keys())

        if not self._chunks:
            raise LexicalError(f"No chunks found in {self.chunks_file}")

        self._average_length = sum(self._lengths) / len(self._lengths)

    def count(self) -> int:
        return len(self._chunks)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _idf(self, term: str) -> float:
        total = len(self._chunks)
        frequency = self._document_frequency.get(term, 0)
        return math.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))

    def _bm25(self, query_terms: Iterable[str], index: int) -> float:
        terms = self._terms[index]
        length = self._lengths[index] or 1
        score = 0.0
        for term in query_terms:
            frequency = terms.get(term, 0)
            if not frequency:
                continue
            denominator = frequency + self.k1 * (
                1.0 - self.b + self.b * length / self._average_length
            )
            score += self._idf(term) * frequency * (self.k1 + 1.0) / denominator
        return score

    def _similarity(self, raw_score: float) -> float:
        if raw_score <= 0:
            return 0.0
        return raw_score / (raw_score + self.score_scale)

    def _make_hit(self, index: int, raw_score: float) -> dict[str, Any]:
        chunk = self._chunks[index]
        similarity = self._similarity(raw_score)
        return {
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "metadata": {
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk.get("doc_id", ""),
                "source_url": chunk.get("source_url", ""),
                "source_title": chunk.get("source_title", ""),
                "section": chunk.get("section", ""),
                "content_type": chunk.get("content_type", ""),
                "scraped_at": chunk.get("scraped_at", ""),
            },
            "distance": max(0.0, 1.0 - similarity),
            "score": similarity,
            "_raw_score": raw_score,
        }

    def _rank(
        self,
        query: str,
        *,
        top_k: int,
        allowed: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        query_terms = tokenize(query)
        if not query_terms:
            return []

        phrase = " ".join(_TOKEN_RE.findall(query.casefold()))
        scored: list[tuple[float, int]] = []
        for index in range(len(self._chunks)):
            if allowed is not None and index not in allowed:
                continue
            raw = self._bm25(query_terms, index)
            if raw <= 0:
                continue
            # Exact phrase matches are strong evidence for FAQ questions.
            if len(phrase) > 4 and phrase in self._chunks[index]["text"].casefold():
                raw += 2.0
            scored.append((raw, index))

        scored.sort(key=lambda item: (-item[0], self._chunks[item[1]]["chunk_id"]))
        return [self._make_hit(index, raw) for raw, index in scored[:top_k]]

    # ------------------------------------------------------------------
    # Public search interface (mirrors ChromaStore)
    # ------------------------------------------------------------------

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        if top_k <= 0:
            raise LexicalError("top_k must be positive")
        return self._rank(query, top_k=top_k)

    def search_facts(
        self,
        query: str,
        *,
        regex: str,
        doc_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if not regex:
            raise LexicalError("regex must not be empty")
        if top_k <= 0:
            raise LexicalError("top_k must be positive")

        try:
            pattern = re.compile(regex, re.IGNORECASE)
        except re.error as exc:
            raise LexicalError(f"Invalid fact regex: {exc}") from exc

        allowed = {
            index
            for index, chunk in enumerate(self._chunks)
            if (doc_id is None or chunk.get("doc_id") == doc_id)
            and pattern.search(str(chunk["text"]))
        }
        if not allowed:
            return []

        hits = self._rank(query, top_k=top_k, allowed=allowed)
        if hits:
            return hits

        # The regex matched but the query terms did not. Return the first
        # matching chunks so sufficiency can still see the requested fact.
        return [self._make_hit(index, 1.0) for index in sorted(allowed)[:top_k]]
