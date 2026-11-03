import json

from src.config import load_settings
from src.rag.lexical import LexicalIndex, tokenize
from src.rag.retriever import Retriever


def _chunk(chunk_id, doc_id, text, section="Overview"):
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "source_url": f"https://example.com/{doc_id}",
        "source_title": doc_id.upper(),
        "section": section,
        "content_type": "paragraph",
        "scraped_at": "2026-11-02T07:03:13Z",
        "text": text,
    }


def _write_chunks(tmp_path):
    rows = [
        _chunk(
            "elss::facts::001",
            "hdfc-elss",
            "HDFC ELSS Tax Saver Fund. Exit load: Nil. Lock-in period: 3 years.",
        ),
        _chunk(
            "loads::overview::001",
            "mf-loads",
            "What are loads? An exit load may apply when units are redeemed early.",
        ),
        _chunk(
            "expenses::overview::001",
            "mf-expenses",
            "The total expense ratio is charged annually by the fund house.",
        ),
    ]
    path = tmp_path / "chunks.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_tokenize_drops_stopwords_and_normalizes_plurals():
    assert tokenize("What are the expense ratios?") == ["expense", "ratio"]


def test_lexical_index_ranks_relevant_chunk(tmp_path):
    index = LexicalIndex(_write_chunks(tmp_path))

    hits = index.search("exit load on HDFC ELSS", top_k=3)

    assert index.count() == 3
    assert hits[0]["chunk_id"] == "elss::facts::001"
    assert hits[0]["score"] > 0.35


def test_lexical_search_facts_filters_by_doc_id(tmp_path):
    index = LexicalIndex(_write_chunks(tmp_path))

    hits = index.search_facts(
        "exit load", regex=r"exit\s+load", doc_id="hdfc-elss", top_k=3
    )

    assert [hit["chunk_id"] for hit in hits] == ["elss::facts::001"]


def test_retriever_switches_to_lexical_on_vercel(tmp_path, monkeypatch):
    settings = load_settings()
    settings = settings.model_copy(
        update={
            "paths": settings.paths.model_copy(
                update={"chunks_file": _write_chunks(tmp_path)}
            )
        }
    )
    monkeypatch.setenv("VERCEL", "1")

    retriever = Retriever(settings=settings, sources=[])

    assert retriever.lexical is True
    assert retriever.store.count() == 3
    assert retriever.retrieve("exit load on HDFC ELSS").results[0].score > 0.35
