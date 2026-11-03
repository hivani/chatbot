import numpy as np
import pytest

from src.rag.store import (
    STORE_METADATA_FIELDS,
    ChromaStore,
    StoreError,
    chunk_metadata,
    sanitize_metadata,
)

COLLECTION = "test_faq"


def _metadata(chunk_id: str, **overrides):
    payload = {
        "chunk_id": chunk_id,
        "doc_id": "test-doc",
        "source_url": "https://groww.in/mutual-funds/test-fund",
        "source_title": "Test Fund",
        "section": "Facts",
        "content_type": "paragraph",
        "scraped_at": "2026-11-01T09:14:22Z",
        "text": "Expense ratio is 1.20 percent.",
        "token_count": 7,
        "content_hash": "abc123",
        "embedding_model": "fake-mini",
        "dim": 2,
    }
    payload.update(overrides)
    return payload


def _store(tmp_path, **kwargs):
    return ChromaStore(tmp_path / "chroma", COLLECTION, **kwargs)


def _upsert(store, ids, vectors, texts, metadatas):
    return store.upsert(
        ids,
        np.asarray(vectors, dtype=np.float32),
        texts,
        metadatas,
    )


# ---------------------------------------------------------------------------
# Metadata sanitization
# ---------------------------------------------------------------------------


def test_sanitize_metadata_drops_none_and_stringifies_nested_values():
    cleaned = sanitize_metadata(
        {
            "keep": "value",
            "count": 3,
            "ratio": 1.2,
            "enabled": True,
            "drop": None,
            "tags": ["a", "b"],
            "nested": {"b": 2, "a": 1},
            "nan": float("nan"),
        }
    )

    assert cleaned["keep"] == "value"
    assert cleaned["count"] == 3
    assert cleaned["ratio"] == 1.2
    assert cleaned["enabled"] is True
    assert "drop" not in cleaned
    assert cleaned["tags"] == "a, b"
    assert cleaned["nested"] == '{"a": 1, "b": 2}'
    assert cleaned["nan"] == "nan"


def test_chunk_metadata_keeps_only_retrieval_fields():
    payload = chunk_metadata(_metadata("c1"), chunk_id="c1")

    assert tuple(payload) == STORE_METADATA_FIELDS
    assert payload["chunk_id"] == "c1"
    assert "text" not in payload
    assert "embedding_model" not in payload


def test_chunk_metadata_requires_all_fields():
    broken = _metadata("c1")
    del broken["source_url"]

    with pytest.raises(StoreError, match="source_url"):
        chunk_metadata(broken, chunk_id="c1")


def test_chunk_metadata_rejects_non_string_field():
    with pytest.raises(StoreError, match="must be strings"):
        chunk_metadata(_metadata("c1", doc_id=7), chunk_id="c1")


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def test_upsert_persists_documents_and_scalar_metadata(tmp_path):
    store = _store(tmp_path)

    written = _upsert(
        store,
        ["c1", "c2"],
        [[1.0, 0.0], [0.0, 1.0]],
        ["first document", "second document"],
        [
            _metadata("c1", section="Facts"),
            _metadata("c2", section="Charges"),
        ],
    )

    assert written == 2
    assert store.count() == 2

    result = store.collection.get(ids=["c1", "c2"])
    assert result["documents"] == ["first document", "second document"]
    stored = {row["chunk_id"]: row for row in result["metadatas"]}
    assert set(stored) == {"c1", "c2"}
    assert set(stored["c1"]) == set(STORE_METADATA_FIELDS)
    assert stored["c2"]["section"] == "Charges"
    assert "text" not in stored["c1"]


def test_upsert_uses_batches_of_100_by_default(tmp_path):
    class _FakeCollection:
        def __init__(self):
            self.batch_sizes = []

        def upsert(self, *, ids, **_kwargs):
            self.batch_sizes.append(len(ids))

    store = _store(tmp_path)
    store._collection = _FakeCollection()

    ids = [f"c{index}" for index in range(205)]
    written = _upsert(
        store,
        ids,
        np.tile([1.0, 0.0], (len(ids), 1)),
        [f"document {index}" for index in range(len(ids))],
        [_metadata(chunk_id) for chunk_id in ids],
    )

    assert written == 205
    assert store._collection.batch_sizes == [100, 100, 5]


def test_upsert_is_idempotent_by_chunk_id(tmp_path):
    store = _store(tmp_path)
    ids = ["c1", "c2"]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    texts = ["first", "second"]
    metadatas = [_metadata("c1"), _metadata("c2")]

    _upsert(store, ids, vectors, texts, metadatas)
    _upsert(store, ids, vectors, texts, metadatas)

    assert store.count() == 2


def test_upsert_updates_existing_chunk_in_place(tmp_path):
    store = _store(tmp_path)
    _upsert(store, ["c1"], [[1.0, 0.0]], ["old text"], [_metadata("c1")])
    _upsert(
        store,
        ["c1"],
        [[0.0, 1.0]],
        ["new text"],
        [_metadata("c1", section="Updated")],
    )

    assert store.count() == 1
    result = store.collection.get(ids=["c1"])
    assert result["documents"] == ["new text"]
    assert result["metadatas"][0]["section"] == "Updated"


def test_upsert_rejects_misaligned_inputs(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="same length"):
        _upsert(
            store,
            ["c1", "c2"],
            [[1.0, 0.0], [0.0, 1.0]],
            ["only one document"],
            [_metadata("c1"), _metadata("c2")],
        )


def test_upsert_rejects_empty_payload(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="empty batch"):
        _upsert(store, [], np.empty((0, 2)), [], [])


def test_upsert_rejects_duplicate_ids(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="Duplicate chunk IDs"):
        _upsert(
            store,
            ["c1", "c1"],
            [[1.0, 0.0], [0.0, 1.0]],
            ["one", "two"],
            [_metadata("c1"), _metadata("c1")],
        )


def test_upsert_rejects_empty_document_text(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="empty document"):
        _upsert(store, ["c1"], [[1.0, 0.0]], ["   "], [_metadata("c1")])


def test_upsert_rejects_non_finite_vectors(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="non-finite"):
        _upsert(
            store,
            ["c1"],
            [[float("nan"), 0.0]],
            ["text"],
            [_metadata("c1")],
        )


# ---------------------------------------------------------------------------
# Collection lifecycle and count
# ---------------------------------------------------------------------------


def test_rebuild_removes_stale_chunks(tmp_path):
    store = _store(tmp_path)
    _upsert(
        store,
        ["c1", "c2"],
        [[1.0, 0.0], [0.0, 1.0]],
        ["one", "two"],
        [_metadata("c1"), _metadata("c2")],
    )
    assert store.count() == 2

    assert store.rebuild() == 0
    assert store.count() == 0

    _upsert(store, ["c3"], [[1.0, 0.0]], ["three"], [_metadata("c3")])
    assert store.count() == 1


def test_assert_count_reports_stale_extra_rows(tmp_path):
    store = _store(tmp_path)
    _upsert(
        store,
        ["stale"],
        [[1.0, 0.0]],
        ["stale"],
        [_metadata("stale")],
    )

    with pytest.raises(StoreError, match="Re-run with --rebuild"):
        store.assert_count(2)


def test_collection_uses_cosine_distance(tmp_path):
    store = _store(tmp_path)

    assert store.collection.metadata["hnsw:space"] == "cosine"


def test_existing_collection_with_wrong_distance_is_rejected(tmp_path):
    path = tmp_path / "chroma"
    first = ChromaStore(path, COLLECTION, distance="l2")
    assert first.count() == 0

    second = ChromaStore(path, COLLECTION, distance="cosine")
    with pytest.raises(StoreError, match="distance"):
        second.count()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_returns_nearest_chunk_first(tmp_path):
    store = _store(tmp_path)
    _upsert(
        store,
        ["east", "north"],
        [[1.0, 0.0], [0.0, 1.0]],
        ["east document", "north document"],
        [_metadata("east"), _metadata("north")],
    )

    hits = store.search(np.asarray([1.0, 0.0], dtype=np.float32), top_k=2)

    assert [hit["chunk_id"] for hit in hits] == ["east", "north"]
    assert hits[0]["distance"] == pytest.approx(0.0, abs=1e-6)
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)
    assert hits[0]["text"] == "east document"
    assert hits[0]["metadata"]["source_url"].endswith("test-fund")


def test_search_limits_to_available_results(tmp_path):
    store = _store(tmp_path)
    _upsert(store, ["c1"], [[1.0, 0.0]], ["one"], [_metadata("c1")])

    assert len(store.search(np.asarray([1.0, 0.0]), top_k=5)) == 1


def test_search_empty_collection_returns_no_hits(tmp_path):
    store = _store(tmp_path)

    assert store.search(np.asarray([1.0, 0.0]), top_k=5) == []


def test_search_facts_is_case_insensitive_and_filters_by_doc(tmp_path):
    store = _store(tmp_path)
    _upsert(
        store,
        ["elss-facts", "midcap-facts", "elss-fund-house"],
        [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]],
        [
            "HDFC ELSS — Facts. Exit load | Nil",
            "HDFC Mid Cap — Facts. Exit load | 1%",
            "HDFC ELSS — Fund house. HDFC Mutual Fund",
        ],
        [
            _metadata("elss-facts", doc_id="hdfc-elss"),
            _metadata("midcap-facts", doc_id="hdfc-mid-cap"),
            _metadata("elss-fund-house", doc_id="hdfc-elss"),
        ],
    )

    hits = store.search_facts(
        np.asarray([1.0, 0.0]),
        regex=r"(?i)exit\s+load",
        doc_id="hdfc-elss",
        top_k=5,
    )

    assert [hit["chunk_id"] for hit in hits] == ["elss-facts"]


def test_search_facts_requires_regex(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="regex"):
        store.search_facts(np.asarray([1.0, 0.0]), regex="")


def test_search_rejects_bad_top_k(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(StoreError, match="top_k"):
        store.search(np.asarray([1.0, 0.0]), top_k=0)
