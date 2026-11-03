import json
from pathlib import Path

import numpy as np
import pytest

from src.ingest.chunker import (
    WhitespaceTokenCounter,
    chunk_documents,
)
from src.ingest.loader import RawDocument, content_hash, utc_now_iso
from src.rag.embedder import (
    EmbeddingError,
    embed_chunks,
    embed_query,
    normalize_vectors,
    read_embeddings,
    write_embeddings,
)

DOC_URL = "https://groww.in/mutual-funds/test-fund"


class _FakeEmbedder:
    model_name = "fake-mini"
    dimension = 4

    def encode(self, texts, *, batch_size=32):
        rows = []
        for index, text in enumerate(texts):
            rows.append(
                [
                    float(len(text) + 1),
                    float((sum(map(ord, text)) % 13) + 1),
                    float((index % 7) + 1),
                    1.0,
                ]
            )
        return np.asarray(rows, dtype=np.float32)


class _WrongRowEmbedder(_FakeEmbedder):
    def encode(self, texts, *, batch_size=32):
        return np.ones((1, self.dimension), dtype=np.float32)


def _doc(blocks: list[dict] | None = None) -> RawDocument:
    text = "Test Fund body"
    return RawDocument(
        doc_id="test-doc",
        url=DOC_URL,
        title="Test Fund",
        category="scheme",
        scraped_at=utc_now_iso(),
        http_status=200,
        content_type="scheme_page",
        blocks=blocks
        or [
            {"kind": "heading", "level": 2, "text": "Facts"},
            {"kind": "paragraph", "text": "Expense ratio is 1.20 percent."},
        ],
        text=text,
        content_hash=content_hash(text),
    )


def _chunks(blocks: list[dict] | None = None):
    return chunk_documents(
        [_doc(blocks)],
        WhitespaceTokenCounter(),
        chunk_size=50,
        chunk_overlap=0,
        max_seq_length=60,
    )


def _two_chunks():
    return _chunks(
        [
            {"kind": "heading", "level": 2, "text": "Facts"},
            {"kind": "paragraph", "text": "Expense ratio is 1.20 percent."},
            {"kind": "heading", "level": 2, "text": "Charges"},
            {"kind": "paragraph", "text": "Exit load is Nil."},
        ]
    )


def test_embed_chunks_returns_aligned_normalized_vectors_and_metadata():
    chunks = _two_chunks()
    assert len(chunks) == 2

    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
        batch_size=2,
    )

    assert ids == [chunk.chunk_id for chunk in chunks]
    assert vectors.shape == (2, 4)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)

    assert [row["chunk_id"] for row in metadata] == ids
    assert metadata[0]["embedding_model"] == "fake-mini"
    assert metadata[0]["dim"] == 4
    assert metadata[0]["text"] == chunks[0].text


def test_embed_chunks_requires_chunks():
    with pytest.raises(EmbeddingError, match="No chunks"):
        embed_chunks([], _FakeEmbedder(), max_seq_length=60)


def test_embed_chunks_refuses_to_truncate_oversized_chunk():
    chunks = _chunks()

    with pytest.raises(EmbeddingError, match="refusing to truncate"):
        embed_chunks(chunks, _FakeEmbedder(), max_seq_length=5)


def test_embed_chunks_rejects_wrong_vector_row_count():
    with pytest.raises(EmbeddingError, match="Expected 2 embedding rows"):
        embed_chunks(
            _two_chunks(),
            _WrongRowEmbedder(),
            max_seq_length=60,
        )


def test_embed_query_returns_one_normalized_vector():
    vector = embed_query("What is the exit load?", _FakeEmbedder())

    assert vector.shape == (4,)
    assert vector.dtype == np.float32
    assert np.isclose(np.linalg.norm(vector), 1.0)


def test_embed_query_rejects_empty_text():
    with pytest.raises(EmbeddingError, match="must not be empty"):
        embed_query("   ", _FakeEmbedder())


def test_normalize_vectors_rejects_zero_vector():
    with pytest.raises(EmbeddingError, match="zero embedding"):
        normalize_vectors(np.zeros((1, 4), dtype=np.float32))


def test_write_embeddings_roundtrips_npz_and_metadata(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )

    npz_path, metadata_path = write_embeddings(ids, vectors, metadata, tmp_path)

    assert npz_path == tmp_path / "embeddings.npz"
    assert metadata_path == tmp_path / "metadata.jsonl"

    with np.load(npz_path) as data:
        assert data["ids"].tolist() == ids
        assert data["vectors"].shape == vectors.shape
        assert data["vectors"].dtype == np.float32
        assert np.allclose(data["vectors"], vectors)

    rows = [
        json.loads(line)
        for line in metadata_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == len(chunks)
    assert rows[0]["chunk_id"] == ids[0]
    assert rows[0]["embedding_model"] == "fake-mini"
    assert rows[0]["dim"] == 4


def test_write_embeddings_rejects_misaligned_metadata(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )
    metadata[0]["chunk_id"] = "someone-else"

    with pytest.raises(EmbeddingError, match="Metadata row 0"):
        write_embeddings(ids, vectors, metadata, tmp_path)


def test_write_embeddings_rejects_dim_mismatch(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )
    metadata[0]["dim"] = 99

    with pytest.raises(EmbeddingError, match="dim=99"):
        write_embeddings(ids, vectors, metadata, tmp_path)


def test_write_embeddings_refuses_empty_output(tmp_path):
    with pytest.raises(EmbeddingError, match="empty embedding set"):
        write_embeddings([], np.empty((0, 4)), [], tmp_path)


def test_embedding_output_files_are_not_left_partial(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )
    write_embeddings(ids, vectors, metadata, tmp_path)

    assert not list(Path(tmp_path).glob(".*.tmp"))


def test_read_embeddings_roundtrips_written_output(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )
    write_embeddings(ids, vectors, metadata, tmp_path)

    loaded_ids, loaded_vectors, loaded_metadata = read_embeddings(tmp_path)

    assert loaded_ids == ids
    assert np.allclose(loaded_vectors, vectors)
    assert [row["chunk_id"] for row in loaded_metadata] == ids


def test_read_embeddings_rejects_misaligned_metadata(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )
    write_embeddings(ids, vectors, metadata, tmp_path)

    metadata_path = tmp_path / "metadata.jsonl"
    rows = [
        json.loads(line)
        for line in metadata_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[1]["chunk_id"] = "someone-else"
    metadata_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EmbeddingError, match="Metadata row 1"):
        read_embeddings(tmp_path)


def test_read_embeddings_requires_files(tmp_path):
    with pytest.raises(EmbeddingError, match="not found"):
        read_embeddings(tmp_path)


def test_read_embeddings_rejects_missing_text(tmp_path):
    chunks = _two_chunks()
    ids, vectors, metadata = embed_chunks(
        chunks,
        _FakeEmbedder(),
        max_seq_length=60,
    )
    write_embeddings(ids, vectors, metadata, tmp_path)

    metadata_path = tmp_path / "metadata.jsonl"
    rows = [
        json.loads(line)
        for line in metadata_path.read_text(encoding="utf-8").splitlines()
    ]
    del rows[0]["text"]
    metadata_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EmbeddingError, match="missing chunk text"):
        read_embeddings(tmp_path)
