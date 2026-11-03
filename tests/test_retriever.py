import numpy as np
import pytest

from src.config import load_settings
from src.ingest.loader import SourceSpec
from src.rag.retriever import (
    RetrievalError,
    Retriever,
    assess_sufficiency,
    chunk_contains_fact,
    detect_fact_types,
    detect_schemes,
)

ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
MIDCAP_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
LOADS_URL = "https://groww.in/mutual-funds/faq/what-are-loads"


def _sources():
    return [
        SourceSpec(
            id="hdfc-elss",
            url=ELSS_URL,
            title="HDFC ELSS Tax Saver Fund Direct Plan Growth",
            category="scheme",
            aliases=("HDFC ELSS", "ELSS Tax Saver", "ELSS"),
        ),
        SourceSpec(
            id="hdfc-mid-cap",
            url=MIDCAP_URL,
            title="HDFC Mid Cap Fund Direct Growth",
            category="scheme",
            aliases=("HDFC Mid Cap", "Mid Cap"),
        ),
        SourceSpec(
            id="hdfc-amc",
            url="https://groww.in/mutual-funds/amc/hdfc-mutual-funds",
            title="HDFC Mutual Fund",
            category="amc",
            aliases=("HDFC MF", "HDFC Mutual Fund"),
        ),
        SourceSpec(
            id="mf-loads",
            url=LOADS_URL,
            title="What are loads?",
            category="faq",
            aliases=("load", "entry load", "exit load"),
        ),
        SourceSpec(
            id="mf-expenses",
            url="https://groww.in/mutual-funds/faq/expenses",
            title="What are the expenses incurred in a Mutual Fund scheme?",
            category="faq",
            aliases=("expense ratio", "expenses", "TER"),
        ),
    ]


class _FakeEmbedder:
    model_name = "fake-mini"
    dimension = 3

    def __init__(self):
        self.seen = []

    def encode(self, texts, *, batch_size=32):
        self.seen.extend(texts)
        return np.ones((len(texts), self.dimension), dtype=np.float32)


class _FakeStore:
    collection_name = "groww_mf_faq"

    def __init__(self, hits):
        self.hits = list(hits)
        self.calls = []

    def search(self, query_embedding, *, top_k=5, where=None):
        self.calls.append({"top_k": top_k, "shape": tuple(query_embedding.shape)})
        return self.hits[:top_k]


class _FakeFactStore(_FakeStore):
    def __init__(self, hits, fact_hits):
        super().__init__(hits)
        self.fact_hits = list(fact_hits)
        self.fact_calls = []

    def search_facts(self, query_embedding, *, regex, doc_id=None, top_k=5):
        self.fact_calls.append(
            {
                "regex": regex,
                "doc_id": doc_id,
                "top_k": top_k,
                "shape": tuple(query_embedding.shape),
            }
        )
        return self.fact_hits[:top_k]


def _hit(
    *,
    chunk_id: str,
    doc_id: str,
    text: str,
    distance: float,
    source_url: str,
    source_title: str = "Test Fund",
    section: str = "Facts",
    content_type: str = "paragraph",
    scraped_at: str = "2026-11-01T09:14:22Z",
):
    return {
        "chunk_id": chunk_id,
        "text": text,
        "distance": distance,
        "score": 1.0 - distance,
        "metadata": {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "source_url": source_url,
            "source_title": source_title,
            "section": section,
            "content_type": content_type,
            "scraped_at": scraped_at,
        },
    }


def _retriever(hits, *, embedder=None, sources=None, store=None):
    return Retriever(
        settings=load_settings(),
        embedder=embedder or _FakeEmbedder(),
        store=store or _FakeStore(hits),
        sources=sources or _sources(),
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_schemes_matches_aliases_case_insensitively():
    assert detect_schemes("what is the EXIT LOAD on hdfc elss?", _sources()) == (
        "hdfc-elss",
    )
    assert detect_schemes("HDFC Mid Cap expense ratio", _sources()) == (
        "hdfc-mid-cap",
    )


def test_detect_schemes_ignores_non_scheme_sources():
    assert detect_schemes("Tell me about HDFC Mutual Fund", _sources()) == ()
    assert detect_schemes("What are loads?", _sources()) == ()


def test_detect_schemes_does_not_match_substrings():
    assert detect_schemes("ELSSX lock-in", _sources()) == ()


def test_detect_fact_types_returns_all_matches():
    assert detect_fact_types("What is the exit load and expense ratio?") == (
        "expense_ratio",
        "exit_load",
    )
    assert detect_fact_types("What is the lock-in for ELSS SIP?") == (
        "sip",
        "lock_in",
    )
    assert detect_fact_types("What is a riskometer?") == ("riskometer",)


def test_chunk_contains_fact_requires_a_requested_term():
    assert chunk_contains_fact("Exit load | Nil", {"exit_load"})
    assert not chunk_contains_fact("Fund house | HDFC", {"exit_load"})
    assert not chunk_contains_fact("anything", set())


# ---------------------------------------------------------------------------
# Retrieval mapping
# ---------------------------------------------------------------------------


def test_retrieve_maps_chunks_and_converts_distance_to_similarity():
    hits = [
        _hit(
            chunk_id="elss::facts::001",
            doc_id="hdfc-elss",
            text="HDFC ELSS — Facts. Exit load | Nil",
            distance=0.20,
            source_url=ELSS_URL,
            section="Facts",
            content_type="table",
        ),
        _hit(
            chunk_id="mf-loads::overview::001",
            doc_id="mf-loads",
            text="What are loads? An exit load may apply.",
            distance=0.45,
            source_url=LOADS_URL,
        ),
    ]
    embedder = _FakeEmbedder()
    retriever = _retriever(hits, embedder=embedder)

    result = retriever.retrieve("What is the exit load on HDFC ELSS?", top_k=2)

    assert result.question == "What is the exit load on HDFC ELSS?"
    assert result.embedding_model == "fake-mini"
    assert result.collection == "groww_mf_faq"
    assert result.top_k == 2
    assert result.sufficient is True
    assert embedder.seen == ["What is the exit load on HDFC ELSS?"]
    assert [chunk.rank for chunk in result.results] == [1, 2]
    assert [chunk.score for chunk in result.results] == pytest.approx([0.80, 0.55])
    assert result.results[0].chunk_id == "elss::facts::001"
    assert result.results[0].source_url == ELSS_URL
    assert result.results[0].content_type == "table"


def test_retrieve_uses_configured_top_k_and_reports_sufficiency_details():
    settings = load_settings()
    hits = [
        _hit(
            chunk_id=f"chunk-{index}",
            doc_id="hdfc-elss",
            text="HDFC ELSS — Facts. Exit load | Nil",
            distance=0.1 * index,
            source_url=ELSS_URL,
        )
        for index in range(1, 8)
    ]
    retriever = _retriever(hits)

    result = retriever.retrieve("HDFC ELSS exit load")

    assert retriever.store.calls[0]["top_k"] == settings.retrieval.top_k
    assert len(result.results) == settings.retrieval.top_k
    assert result.to_dict()["sufficiency"]["detected_scheme_ids"] == ["hdfc-elss"]
    assert result.to_dict()["sufficiency"]["detected_fact_types"] == ["exit_load"]
    assert result.to_dict()["query"] == "HDFC ELSS exit load"


def test_retrieve_rejects_empty_question():
    retriever = _retriever([])

    with pytest.raises(RetrievalError, match="must not be empty"):
        retriever.retrieve("   ")


def test_retrieve_rejects_bad_limits():
    retriever = _retriever([])

    with pytest.raises(RetrievalError, match="top_k"):
        retriever.retrieve("HDFC ELSS exit load", top_k=0)
    with pytest.raises(RetrievalError, match="min_score"):
        retriever.retrieve("HDFC ELSS exit load", min_score=1.5)


def test_retrieve_adds_filtered_fact_chunk_when_vector_search_misses_it():
    vector_hits = [
        _hit(
            chunk_id="elss-fund-house",
            doc_id="hdfc-elss",
            text="HDFC ELSS — Fund house. HDFC Mutual Fund",
            distance=0.15,
            source_url=ELSS_URL,
        )
    ]
    fact_hit = _hit(
        chunk_id="elss-overview",
        doc_id="hdfc-elss",
        text="HDFC ELSS — Overview (table). Exit load | Nil",
        distance=0.44,
        source_url=ELSS_URL,
        content_type="table",
    )
    store = _FakeFactStore(vector_hits, [fact_hit])
    retriever = _retriever([], store=store)

    result = retriever.retrieve("HDFC ELSS exit load", top_k=5)

    assert result.sufficient is True
    assert [chunk.chunk_id for chunk in result.results] == [
        "elss-fund-house",
        "elss-overview",
    ]
    assert [chunk.rank for chunk in result.results] == [1, 2]
    assert store.fact_calls == [
        {
            "regex": r"(?i)(?:exit\s+load|entry\s+load)",
            "doc_id": "hdfc-elss",
            "top_k": 5,
            "shape": (3,),
        }
    ]


def test_retrieve_deduplicates_filtered_fact_chunks():
    fact_hit = _hit(
        chunk_id="elss-overview",
        doc_id="hdfc-elss",
        text="HDFC ELSS — Overview (table). Exit load | Nil",
        distance=0.2,
        source_url=ELSS_URL,
    )
    store = _FakeFactStore([fact_hit], [fact_hit])
    retriever = _retriever([], store=store)

    result = retriever.retrieve("HDFC ELSS exit load")

    assert [chunk.chunk_id for chunk in result.results] == ["elss-overview"]


def test_retrieve_does_not_filter_facts_for_generic_questions():
    hit = _hit(
        chunk_id="loads",
        doc_id="mf-loads",
        text="What are loads? An exit load may apply.",
        distance=0.2,
        source_url=LOADS_URL,
    )
    store = _FakeFactStore([hit], [])
    retriever = _retriever([], store=store)

    result = retriever.retrieve("What is an exit load?")

    assert result.sufficient is True
    assert [chunk.chunk_id for chunk in result.results] == ["loads"]
    assert store.fact_calls[0]["doc_id"] is None
    assert store.fact_calls[0]["regex"] == r"(?i)(?:exit\s+load|entry\s+load)"


# ---------------------------------------------------------------------------
# Sufficiency
# ---------------------------------------------------------------------------


def test_sufficient_when_scheme_and_fact_are_in_top_results():
    hits = [
        _hit(
            chunk_id="loads-general",
            doc_id="mf-loads",
            text="What are loads? An exit load is charged on early redemption.",
            distance=0.2,
            source_url=LOADS_URL,
        ),
        _hit(
            chunk_id="elss-facts",
            doc_id="hdfc-elss",
            text="HDFC ELSS — Facts. Exit load | Nil",
            distance=0.3,
            source_url=ELSS_URL,
        ),
    ]

    result = _retriever(hits).retrieve("What is the exit load on HDFC ELSS?")

    assert result.sufficient is True
    assert result.sufficiency.reason is None
    assert result.sufficiency.matching_scheme_chunk_ids == ("elss-facts",)
    assert result.sufficiency.matching_fact_chunk_ids == (
        "loads-general",
        "elss-facts",
    )
    assert result.sufficiency.suggested_url == ELSS_URL


def test_insufficient_when_top_score_is_below_threshold():
    hits = [
        _hit(
            chunk_id="weak",
            doc_id="hdfc-elss",
            text="HDFC ELSS — Fund house. HDFC Mutual Fund",
            distance=0.9,
            source_url=ELSS_URL,
        )
    ]

    result = _retriever(hits).retrieve(
        "HDFC ELSS exit load",
        min_score=0.35,
    )

    assert result.sufficient is False
    assert result.sufficiency.reason == "below_score_threshold"
    assert result.sufficiency.suggested_url == ELSS_URL


def test_insufficient_when_named_scheme_is_missing_from_results():
    hits = [
        _hit(
            chunk_id="midcap-facts",
            doc_id="hdfc-mid-cap",
            text="HDFC Mid Cap — Facts. Exit load | 1%",
            distance=0.1,
            source_url=MIDCAP_URL,
        )
    ]

    result = _retriever(hits).retrieve("HDFC ELSS exit load")

    assert result.sufficient is False
    assert result.sufficiency.reason == "scheme_not_in_results"
    assert result.sufficiency.suggested_url == ELSS_URL


def test_insufficient_when_requested_fact_is_missing_from_results():
    hits = [
        _hit(
            chunk_id="elss-fund-house",
            doc_id="hdfc-elss",
            text="HDFC ELSS — Fund house. HDFC Mutual Fund",
            distance=0.1,
            source_url=ELSS_URL,
        )
    ]

    result = _retriever(hits).retrieve("HDFC ELSS expense ratio")

    assert result.sufficient is False
    assert result.sufficiency.reason == "fact_not_in_results"
    assert result.sufficiency.suggested_url == ELSS_URL


def test_insufficient_with_no_results_returns_official_fact_page():
    result = _retriever([]).retrieve("What is an exit load?")

    assert result.sufficient is False
    assert result.sufficiency.reason == "no_results"
    assert result.sufficiency.suggested_url == LOADS_URL


def test_insufficient_when_no_known_scheme_or_fact_is_recognised():
    hits = [
        _hit(
            chunk_id="amc-overview",
            doc_id="hdfc-amc",
            text="HDFC Mutual Fund — Overview. Key information.",
            distance=0.2,
            source_url="https://groww.in/mutual-funds/amc/hdfc-mutual-funds",
        )
    ]

    result = _retriever(hits).retrieve(
        "What is the NAV of ICICI Prudential Bluechip Fund?"
    )

    assert result.sufficient is False
    assert result.sufficiency.reason == "no_scheme_or_fact"
    assert result.sufficiency.suggested_url.endswith("hdfc-mutual-funds")


def test_generic_fact_question_can_be_sufficient_without_a_scheme():
    hits = [
        _hit(
            chunk_id="loads",
            doc_id="mf-loads",
            text="What are loads? An exit load may apply when units are redeemed.",
            distance=0.2,
            source_url=LOADS_URL,
        )
    ]

    result = _retriever(hits).retrieve("What is an exit load?")

    assert result.sufficient is True
    assert result.sufficiency.detected_scheme_ids == ()
    assert result.sufficiency.detected_fact_types == ("exit_load",)


def test_assess_sufficiency_reports_score_margin():
    hits = [
        _hit(
            chunk_id="first",
            doc_id="hdfc-elss",
            text="Exit load | Nil",
            distance=0.2,
            source_url=ELSS_URL,
        ),
        _hit(
            chunk_id="second",
            doc_id="hdfc-elss",
            text="Exit load | Nil",
            distance=0.5,
            source_url=ELSS_URL,
        ),
    ]
    retriever = _retriever(hits)
    result = retriever.retrieve("HDFC ELSS exit load")
    chunks = result.results

    sufficiency = assess_sufficiency(
        "HDFC ELSS exit load",
        chunks,
        _sources(),
        min_score=0.35,
    )

    assert sufficiency.score_margin == pytest.approx(0.3)
    assert sufficiency.top_score == pytest.approx(0.8)
