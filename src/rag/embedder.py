"""Embed chunks and queries with the configured sentence-transformer model.

Phase 5 of the ingest pipeline. The same model and normalization path must be
used for corpus ingestion and query embedding (phase 7), otherwise cosine
scores are not comparable.

Outputs (under ``data/embeddings``):

* ``embeddings.npz`` — ``ids`` (chunk IDs) and ``vectors`` (float32, L2-normalized)
* ``metadata.jsonl`` — chunk metadata aligned by ``chunk_id`` plus
  ``embedding_model`` and ``dim``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from src.ingest.chunker import Chunk

EMBEDDINGS_FILENAME = "embeddings.npz"
METADATA_FILENAME = "metadata.jsonl"


class EmbeddingError(RuntimeError):
    """Raised when chunks cannot be embedded or output validation fails."""


class TextEmbedder(Protocol):
    """Minimal interface needed by the ingest and query paths."""

    model_name: str
    dimension: int

    def encode(self, texts: Sequence[str], *, batch_size: int) -> np.ndarray:
        """Return one embedding row per input text."""


class SentenceTransformerEmbedder:
    """SentenceTransformer adapter with explicit float32 output."""

    def __init__(
        self,
        model_name: str,
        *,
        max_seq_length: int | None = None,
        device: str | None = None,
    ):
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name, device=device)
        except Exception as exc:  # noqa: BLE001 - surface a clear embedding error
            raise EmbeddingError(
                f"Could not load embedding model {model_name!r}: {exc}"
            ) from exc

        if max_seq_length is not None:
            model.max_seq_length = int(max_seq_length)

        get_dimension = getattr(model, "get_embedding_dimension", None)
        if get_dimension is None:
            # Older sentence-transformers releases use the previous name.
            get_dimension = model.get_sentence_embedding_dimension
        dimension = get_dimension()
        if not dimension:
            raise EmbeddingError(
                f"Embedding model {model_name!r} did not report a dimension"
            )

        self._model = model
        self.model_name = model_name
        self.dimension = int(dimension)

    def count_tokens(self, text: str) -> int:
        """Count tokens including model special tokens (no truncation)."""

        encoded = self._model.tokenizer(
            text,
            add_special_tokens=True,
            truncation=False,
            verbose=False,
        )
        return len(encoded["input_ids"])

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 32,
    ) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        try:
            vectors = self._model.encode(
                list(texts),
                batch_size=batch_size,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001 - wrap model/runtime failures
            raise EmbeddingError(
                f"Embedding model {self.model_name!r} failed: {exc}"
            ) from exc

        return np.asarray(vectors, dtype=np.float32)


def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize one vector or each row of a matrix."""

    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2:
        raise EmbeddingError(
            f"Embeddings must be 1-D or 2-D, got shape {array.shape}"
        )

    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise EmbeddingError("Cannot L2-normalize a zero embedding vector")

    return (array / norms).astype(np.float32)


def _validate_vectors(
    vectors: np.ndarray,
    *,
    expected_rows: int,
    expected_dim: int | None,
) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2:
        raise EmbeddingError(
            f"Embeddings must be a 2-D matrix, got shape {array.shape}"
        )
    if array.shape[0] != expected_rows:
        raise EmbeddingError(
            f"Expected {expected_rows} embedding rows, got {array.shape[0]}"
        )
    if array.shape[1] <= 0:
        raise EmbeddingError("Embedding dimension must be positive")
    if expected_dim is not None and array.shape[1] != expected_dim:
        raise EmbeddingError(
            f"Embedding dimension mismatch: model reports {expected_dim}, "
            f"vectors have {array.shape[1]}"
        )
    if not np.isfinite(array).all():
        raise EmbeddingError("Embeddings contain non-finite values")
    return array


def embed_chunks(
    chunks: Sequence[Chunk],
    embedder: TextEmbedder,
    *,
    max_seq_length: int,
    batch_size: int = 32,
    normalize: bool = True,
) -> tuple[list[str], np.ndarray, list[dict]]:
    """Embed chunks and return aligned ``(ids, vectors, metadata)``."""

    if not chunks:
        raise EmbeddingError("No chunks to embed")
    if batch_size <= 0:
        raise EmbeddingError("batch_size must be positive")

    for chunk in chunks:
        if chunk.token_count > max_seq_length:
            raise EmbeddingError(
                f"Chunk {chunk.chunk_id} has {chunk.token_count} tokens, "
                f"above max_seq_length={max_seq_length}; refusing to truncate"
            )
        if not chunk.text.strip():
            raise EmbeddingError(f"Chunk {chunk.chunk_id} has empty text")

    vectors = embedder.encode(
        [chunk.text for chunk in chunks],
        batch_size=batch_size,
    )
    vectors = _validate_vectors(
        vectors,
        expected_rows=len(chunks),
        expected_dim=getattr(embedder, "dimension", None),
    )

    if normalize:
        vectors = normalize_vectors(vectors)

    dim = int(vectors.shape[1])
    metadata = [
        {
            **chunk.to_dict(),
            "embedding_model": embedder.model_name,
            "dim": dim,
        }
        for chunk in chunks
    ]
    return [chunk.chunk_id for chunk in chunks], vectors, metadata


def embed_query(
    text: str,
    embedder: TextEmbedder,
    *,
    normalize: bool = True,
) -> np.ndarray:
    """Embed a single query with the same model and normalization as chunks."""

    if not text.strip():
        raise EmbeddingError("Query text must not be empty")

    vector = np.asarray(
        embedder.encode([text], batch_size=1),
        dtype=np.float32,
    )
    vector = _validate_vectors(
        vector,
        expected_rows=1,
        expected_dim=getattr(embedder, "dimension", None),
    )[0]

    if normalize:
        vector = normalize_vectors(vector)[0]
    return vector.astype(np.float32)


def write_embeddings(
    ids: Sequence[str],
    vectors: np.ndarray,
    metadata: Sequence[dict],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Write ``embeddings.npz`` and ``metadata.jsonl`` atomically."""

    id_list = list(ids)
    vector_array = np.asarray(vectors, dtype=np.float32)
    metadata_list = list(metadata)

    if not id_list:
        raise EmbeddingError("Refusing to write an empty embedding set")
    if len(id_list) != len(vector_array):
        raise EmbeddingError(
            "ids and vectors must have the same length: "
            f"{len(id_list)} != {len(vector_array)}"
        )
    if len(id_list) != len(metadata_list):
        raise EmbeddingError(
            "ids and metadata must have the same length: "
            f"{len(id_list)} != {len(metadata_list)}"
        )
    if len(set(id_list)) != len(id_list):
        raise EmbeddingError("Duplicate chunk IDs in embedding output")
    if vector_array.ndim != 2 or vector_array.shape[1] <= 0:
        raise EmbeddingError(
            f"vectors must be a 2-D matrix, got shape {vector_array.shape}"
        )

    dim = int(vector_array.shape[1])
    for index, (chunk_id, row) in enumerate(zip(id_list, metadata_list)):
        if row.get("chunk_id") != chunk_id:
            raise EmbeddingError(
                f"Metadata row {index} is for {row.get('chunk_id')!r}, "
                f"expected {chunk_id!r}"
            )
        if row.get("dim") != dim:
            raise EmbeddingError(
                f"Metadata row {index} has dim={row.get('dim')!r}, expected {dim}"
            )
        if not row.get("embedding_model"):
            raise EmbeddingError(
                f"Metadata row {index} is missing 'embedding_model'"
            )

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    npz_path = directory / EMBEDDINGS_FILENAME
    metadata_path = directory / METADATA_FILENAME

    npz_temporary = directory / f".{EMBEDDINGS_FILENAME}.tmp"
    with npz_temporary.open("wb") as handle:
        np.savez(
            handle,
            ids=np.asarray(id_list, dtype=str),
            vectors=vector_array,
        )
    npz_temporary.replace(npz_path)

    metadata_temporary = directory / f".{METADATA_FILENAME}.tmp"
    with metadata_temporary.open("w", encoding="utf-8") as handle:
        for row in metadata_list:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    metadata_temporary.replace(metadata_path)

    return npz_path, metadata_path


def read_embeddings(
    output_dir: str | Path,
) -> tuple[list[str], np.ndarray, list[dict]]:
    """Read and validate ``embeddings.npz`` + ``metadata.jsonl``.

    Used by the index stage so a stale, partial, or misaligned embedding run
    cannot be written into Chroma.
    """

    directory = Path(output_dir)
    npz_path = directory / EMBEDDINGS_FILENAME
    metadata_path = directory / METADATA_FILENAME

    if not npz_path.exists():
        raise EmbeddingError(f"Embeddings file not found: {npz_path}")
    if not metadata_path.exists():
        raise EmbeddingError(f"Embedding metadata not found: {metadata_path}")

    try:
        with np.load(npz_path, allow_pickle=False) as data:
            missing = {"ids", "vectors"} - set(data.files)
            if missing:
                raise EmbeddingError(
                    f"Embeddings file is missing array(s): {', '.join(sorted(missing))}"
                )
            ids = [str(value) for value in data["ids"].tolist()]
            vectors = np.asarray(data["vectors"], dtype=np.float32)
    except EmbeddingError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise EmbeddingError(f"Could not read embeddings file {npz_path}: {exc}") from exc

    try:
        metadata = [
            json.loads(line)
            for line in metadata_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingError(
            f"Could not read embedding metadata {metadata_path}: {exc}"
        ) from exc

    if not ids:
        raise EmbeddingError(f"Embeddings file has no rows: {npz_path}")
    if vectors.ndim != 2 or vectors.shape[0] != len(ids):
        raise EmbeddingError(
            f"Embeddings shape {vectors.shape} does not match {len(ids)} ids"
        )
    if not np.isfinite(vectors).all():
        raise EmbeddingError("Embeddings contain non-finite values")
    if len(set(ids)) != len(ids):
        raise EmbeddingError("Duplicate chunk IDs in embeddings file")
    if len(metadata) != len(ids):
        raise EmbeddingError(
            f"Embedding metadata has {len(metadata)} rows, expected {len(ids)}"
        )

    dim = int(vectors.shape[1])
    for index, (chunk_id, row) in enumerate(zip(ids, metadata)):
        if not isinstance(row, dict):
            raise EmbeddingError(f"Metadata row {index} must be a JSON object")
        if row.get("chunk_id") != chunk_id:
            raise EmbeddingError(
                f"Metadata row {index} is for {row.get('chunk_id')!r}, "
                f"expected {chunk_id!r}"
            )
        if row.get("dim") != dim:
            raise EmbeddingError(
                f"Metadata row {index} has dim={row.get('dim')!r}, expected {dim}"
            )
        if not row.get("embedding_model"):
            raise EmbeddingError(
                f"Metadata row {index} is missing 'embedding_model'"
            )
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise EmbeddingError(f"Metadata row {index} is missing chunk text")

    return ids, vectors.astype(np.float32), metadata
