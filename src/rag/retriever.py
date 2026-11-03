"""Query-time retrieval and sufficiency checks.

Phase 7 (retrieval portion). The retriever embeds a question with the same
model used during ingestion, searches the same Chroma collection, converts
cosine distance to similarity, and decides whether the retrieved context is
strong enough to answer.

It deliberately stops before generation: guardrails, prompting, validation,
and artifacts are orchestrated later. The output contract mirrors the
``02_retrieval.json`` artifact described in ``implementation.md``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.config import Settings, load_settings
from src.ingest.loader import SourceSpec, load_sources


def _lexical_mode() -> bool:
    """Use BM25 when the vector stack is unavailable or too large to ship.

    Vercel's Python bundle cannot hold torch + transformers, so functions set
    ``VERCEL=1`` and fall back to the committed chunk file. Local, Streamlit,
    and CLI runs keep using Chroma unless explicitly overridden.
    """

    if os.getenv("GROWCHAT_RETRIEVER", "").strip().casefold() == "lexical":
        return True
    return bool(os.getenv("VERCEL"))


# Fact types named in the phase 7 sufficiency rules. Each type is matched in
# both the question and the retrieved chunk text.
FACT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "expense_ratio": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bexpense\s+ratio\b",
            r"\btotal\s+expense\s+ratio\b",
            r"\bexpenses?\b",
            r"\bter\b",
        )
    ),
    "exit_load": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bexit\s+load\b",
            r"\bentry\s+load\b",
            r"\bloads?\b",
        )
    ),
    "sip": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bsip\b",
            r"\bsystematic\s+investment\s+plan\b",
        )
    ),
    "lock_in": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (r"\block[\s-]?in\b",)
    ),
    "riskometer": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\briskometer\b",
            r"\brisk[\s-]?(?:level|levels|rating)?\b",
        )
    ),
    "benchmark": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (r"\bbenchmarks?\b", r"\bbenchmarking\b")
    ),
    "statement": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bstatements?\b",
            r"\bcapital\s+gains?\s+statement\b",
            r"\bconsolidated\s+account\s+statement\b",
            r"\bcas\b",
        )
    ),
}

# Fallback official pages for generic "what is X?" questions when retrieval has
# no hit. These ids exist in data/sources.csv.
FACT_SOURCE_IDS: dict[str, str] = {
    "expense_ratio": "mf-expenses",
    "exit_load": "mf-loads",
    "sip": "mf-sip",
    "lock_in": "mf-lock-in",
    "riskometer": "mf-riskometer",
    "statement": "mf-capital-gain-statement",
}

# Case-insensitive regexes used for a supplemental filtered Chroma query. A
# small table row ("Expense ratio | 0.75%") can rank below more verbose prose;
# this keeps the requested fact available without leaving the same collection.
FACT_SEARCH_PATTERNS: dict[str, str] = {
    "expense_ratio": r"total\s+expense\s+ratio|expense\s+ratio|expenses?",
    "exit_load": r"exit\s+load|entry\s+load",
    "sip": r"systematic\s+investment\s+plan|\bsip\b",
    "lock_in": r"lock[\s-]?in",
    "riskometer": r"riskometer|\brisk\b",
    "benchmark": r"benchmark",
    "statement": r"statement",
}


class RetrievalError(RuntimeError):
    """Raised when a query cannot be retrieved safely."""


@dataclass(frozen=True)
class RetrievedChunk:
    """One Chroma hit with the metadata needed for citation and display."""

    rank: int
    chunk_id: str
    score: float
    distance: float
    text: str
    doc_id: str
    source_url: str
    source_title: str
    section: str
    content_type: str
    scraped_at: str

    @classmethod
    def from_hit(cls, rank: int, hit: Mapping[str, Any]) -> "RetrievedChunk":
        metadata = dict(hit.get("metadata") or {})
        distance = float(hit.get("distance", 1.0))
        score = 1.0 - distance

        chunk_id = str(hit.get("chunk_id") or metadata.get("chunk_id") or "")
        if not chunk_id:
            raise RetrievalError("Retrieved chunk is missing chunk_id")

        return cls(
            rank=rank,
            chunk_id=chunk_id,
            score=score,
            distance=distance,
            text=str(hit.get("text") or ""),
            doc_id=str(metadata.get("doc_id") or ""),
            source_url=str(metadata.get("source_url") or ""),
            source_title=str(metadata.get("source_title") or ""),
            section=str(metadata.get("section") or ""),
            content_type=str(metadata.get("content_type") or ""),
            scraped_at=str(metadata.get("scraped_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "score": round(self.score, 6),
            "distance": round(self.distance, 6),
            "doc_id": self.doc_id,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "section": self.section,
            "content_type": self.content_type,
            "scraped_at": self.scraped_at,
            "text": self.text,
        }


@dataclass(frozen=True)
class Sufficiency:
    """Why retrieval is or is not enough to answer a question."""

    sufficient: bool
    reason: str | None
    top_score: float | None
    score_margin: float | None
    detected_scheme_ids: tuple[str, ...] = ()
    detected_fact_types: tuple[str, ...] = ()
    matching_scheme_chunk_ids: tuple[str, ...] = ()
    matching_fact_chunk_ids: tuple[str, ...] = ()
    suggested_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "reason": self.reason,
            "top_score": (
                round(self.top_score, 6) if self.top_score is not None else None
            ),
            "score_margin": (
                round(self.score_margin, 6)
                if self.score_margin is not None
                else None
            ),
            "detected_scheme_ids": list(self.detected_scheme_ids),
            "detected_fact_types": list(self.detected_fact_types),
            "matching_scheme_chunk_ids": list(self.matching_scheme_chunk_ids),
            "matching_fact_chunk_ids": list(self.matching_fact_chunk_ids),
            "suggested_url": self.suggested_url,
        }


@dataclass(frozen=True)
class RetrievalResult:
    """Full retrieval output for one query (the 02_retrieval artifact)."""

    question: str
    embedding_model: str
    collection: str
    top_k: int
    min_score: float
    results: tuple[RetrievedChunk, ...]
    sufficiency: Sufficiency

    @property
    def sufficient(self) -> bool:
        return self.sufficiency.sufficient

    @property
    def closest_official_page(self) -> str | None:
        return self.sufficiency.suggested_url

    @property
    def preferred_chunk(self) -> RetrievedChunk | None:
        """The most specific chunk to cite for this question."""

        return _best_evidence(
            self.results,
            self.sufficiency.detected_scheme_ids,
            self.sufficiency.detected_fact_types,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.question,
            "embedding_model": self.embedding_model,
            "collection": self.collection,
            "top_k": self.top_k,
            "min_score": self.min_score,
            "results": [result.to_dict() for result in self.results],
            "sufficient": self.sufficient,
            "sufficiency": self.sufficiency.to_dict(),
        }


# ---------------------------------------------------------------------------
# Question and chunk classification
# ---------------------------------------------------------------------------


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    pattern = (
        r"(?<![a-z0-9])" + re.escape(phrase.casefold()) + r"(?![a-z0-9])"
    )
    return re.search(pattern, text.casefold()) is not None


def _fact_search_regex(fact_types: Iterable[str]) -> str | None:
    patterns = [
        FACT_SEARCH_PATTERNS[fact_type]
        for fact_type in fact_types
        if fact_type in FACT_SEARCH_PATTERNS
    ]
    if not patterns:
        return None
    return r"(?i)(?:" + "|".join(patterns) + r")"


def detect_schemes(
    question: str,
    sources: Sequence[SourceSpec],
) -> tuple[str, ...]:
    """Return scheme ids explicitly named or aliased in ``question``."""

    matched: list[tuple[int, str]] = []
    seen: set[str] = set()

    for spec in sources:
        if spec.category != "scheme" or spec.id in seen:
            continue
        terms = {spec.title, *spec.aliases}
        best_length = 0
        for term in terms:
            if _contains_phrase(question, term):
                best_length = max(best_length, len(term))
        if best_length:
            matched.append((best_length, spec.id))
            seen.add(spec.id)

    matched.sort(key=lambda item: (-item[0], item[1]))
    return tuple(doc_id for _length, doc_id in matched)


def detect_fact_types(question: str) -> tuple[str, ...]:
    """Return the fact types the question asks about."""

    detected = [
        fact_type
        for fact_type, patterns in FACT_PATTERNS.items()
        if any(pattern.search(question) for pattern in patterns)
    ]
    return tuple(detected)


def chunk_contains_fact(text: str, fact_types: Iterable[str]) -> bool:
    """True when ``text`` contains at least one term for a requested fact."""

    return any(
        pattern.search(text)
        for fact_type in fact_types
        for pattern in FACT_PATTERNS.get(fact_type, ())
    )


def _scheme_url(
    scheme_ids: Iterable[str],
    sources: Sequence[SourceSpec],
) -> str | None:
    wanted = set(scheme_ids)
    for spec in sources:
        if spec.id in wanted:
            return spec.url
    return None


def _fact_url(
    fact_types: Iterable[str],
    sources: Sequence[SourceSpec],
) -> str | None:
    fact_list = list(fact_types)
    by_id = {spec.id: spec for spec in sources}
    for fact_type in fact_list:
        source_id = FACT_SOURCE_IDS.get(fact_type)
        if source_id and source_id in by_id:
            return by_id[source_id].url

    for fact_type in fact_list:
        patterns = FACT_PATTERNS.get(fact_type, ())
        for spec in sources:
            if spec.category == "scheme":
                continue
            terms = (spec.title, *spec.aliases)
            if any(
                pattern.search(term)
                for pattern in patterns
                for term in terms
            ):
                return spec.url
    return None


def _best_evidence(
    results: Sequence[RetrievedChunk],
    scheme_ids: Iterable[str],
    fact_types: Iterable[str],
) -> RetrievedChunk | None:
    """Pick the most specific chunk for citation when answering."""

    scheme_set = set(scheme_ids)
    fact_list = list(fact_types)

    if scheme_set and fact_list:
        for result in results:
            if result.doc_id in scheme_set and chunk_contains_fact(
                result.text, fact_list
            ):
                return result
    if scheme_set:
        for result in results:
            if result.doc_id in scheme_set:
                return result
    if fact_list:
        for result in results:
            if chunk_contains_fact(result.text, fact_list):
                return result
    return results[0] if results else None


def assess_sufficiency(
    question: str,
    results: Sequence[RetrievedChunk],
    sources: Sequence[SourceSpec],
    *,
    min_score: float,
) -> Sufficiency:
    """Apply the phase 7 sufficiency rules to retrieved chunks."""

    scheme_ids = detect_schemes(question, sources)
    fact_types = detect_fact_types(question)

    top_score = results[0].score if results else None
    score_margin = (
        results[0].score - results[1].score if len(results) > 1 else None
    )

    matching_scheme = tuple(
        result.chunk_id
        for result in results
        if result.doc_id in scheme_ids
    )
    matching_fact = tuple(
        result.chunk_id
        for result in results
        if chunk_contains_fact(result.text, fact_types)
    )

    reason: str | None = None
    if not results:
        reason = "no_results"
    elif top_score is None or top_score < min_score:
        reason = "below_score_threshold"
    elif not scheme_ids and not fact_types:
        reason = "no_scheme_or_fact"
    elif scheme_ids and not matching_scheme:
        reason = "scheme_not_in_results"
    elif fact_types and not matching_fact:
        reason = "fact_not_in_results"

    sufficient = reason is None

    if sufficient and results:
        preferred = _best_evidence(results, scheme_ids, fact_types)
        suggested_url = preferred.source_url if preferred else None
    elif scheme_ids:
        suggested_url = _scheme_url(scheme_ids, sources)
    elif fact_types:
        suggested_url = _fact_url(fact_types, sources)
    elif results:
        suggested_url = results[0].source_url or None
    else:
        suggested_url = None

    return Sufficiency(
        sufficient=sufficient,
        reason=reason,
        top_score=top_score,
        score_margin=score_margin,
        detected_scheme_ids=scheme_ids,
        detected_fact_types=fact_types,
        matching_scheme_chunk_ids=matching_scheme,
        matching_fact_chunk_ids=matching_fact,
        suggested_url=suggested_url,
    )


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


class Retriever:
    """Embed a question, retrieve top-k chunks, and check sufficiency."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedder: Any | None = None,
        store: Any | None = None,
        sources: Sequence[SourceSpec] | None = None,
    ):
        self.settings = settings or load_settings()
        # Injected stores/embedders mean a test or caller already chose the
        # vector path; never override them with the serverless fallback.
        self.lexical = store is None and embedder is None and _lexical_mode()

        if self.lexical:
            from src.rag.lexical import LexicalIndex

            self.embedder = None
            self.store = LexicalIndex(self.settings.paths.chunks_file)
        else:
            from src.rag.embedder import SentenceTransformerEmbedder
            from src.rag.store import ChromaStore

            self.embedder = embedder or SentenceTransformerEmbedder(
                self.settings.embedding.model,
                max_seq_length=self.settings.embedding.max_seq_length,
            )
            self.store = store or ChromaStore(
                self.settings.vector_store.persist_path,
                self.settings.vector_store.collection,
                distance=self.settings.vector_store.distance,
            )

        self.sources = (
            list(sources)
            if sources is not None
            else load_sources(self.settings.paths.sources)
        )

    def retrieve(
        self,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Retrieve and assess context for one question."""

        cleaned = question.strip() if isinstance(question, str) else ""
        if not cleaned:
            raise RetrievalError("Question must not be empty")

        limit = self.settings.retrieval.top_k if top_k is None else top_k
        threshold = (
            self.settings.retrieval.min_score if min_score is None else min_score
        )
        if limit <= 0:
            raise RetrievalError("top_k must be positive")
        if not 0.0 <= threshold <= 1.0:
            raise RetrievalError("min_score must be between 0.0 and 1.0")

        fact_types = detect_fact_types(cleaned)
        fact_regex = _fact_search_regex(fact_types)

        if self.lexical:
            hits = list(self.store.search(cleaned, top_k=limit))
            fact_query: Any = cleaned
        else:
            from src.rag.embedder import embed_query

            query_vector = embed_query(
                cleaned,
                self.embedder,
                normalize=self.settings.embedding.normalize,
            )
            hits = list(self.store.search(query_vector, top_k=limit))
            fact_query = query_vector

        # When the question names a fact, a filtered query in the same index
        # ensures a compact fact row (e.g. "Exit load | Nil") is not crowded
        # out by long prose chunks.
        if fact_regex and hasattr(self.store, "search_facts"):
            scheme_ids = detect_schemes(cleaned, self.sources)
            supplements: list[Mapping[str, Any]] = []
            if scheme_ids:
                for scheme_id in scheme_ids:
                    supplements.extend(
                        self.store.search_facts(
                            fact_query,
                            regex=fact_regex,
                            doc_id=scheme_id,
                            top_k=limit,
                        )
                    )
            else:
                supplements.extend(
                    self.store.search_facts(
                        fact_query,
                        regex=fact_regex,
                        top_k=limit,
                    )
                )

            seen_ids = {
                str(hit.get("chunk_id") or (hit.get("metadata") or {}).get("chunk_id"))
                for hit in hits
            }
            for supplement in supplements:
                chunk_id = str(
                    supplement.get("chunk_id")
                    or (supplement.get("metadata") or {}).get("chunk_id")
                )
                if chunk_id and chunk_id not in seen_ids:
                    hits.append(supplement)
                    seen_ids.add(chunk_id)

        hits.sort(key=lambda hit: float(hit.get("distance", 1.0)))

        results = tuple(
            RetrievedChunk.from_hit(rank, hit)
            for rank, hit in enumerate(hits, start=1)
        )
        sufficiency = assess_sufficiency(
            cleaned,
            results,
            self.sources,
            min_score=threshold,
        )

        return RetrievalResult(
            question=cleaned,
            embedding_model=(
                "lexical-bm25" if self.lexical else self.embedder.model_name
            ),
            collection=getattr(
                self.store, "collection_name", self.settings.vector_store.collection
            ),
            top_k=limit,
            min_score=threshold,
            results=results,
            sufficiency=sufficiency,
        )
