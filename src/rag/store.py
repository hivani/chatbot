"""Persist embedded chunks in a ChromaDB collection.

Phase 6 of the ingest pipeline. The store is deliberately small: it owns the
Chroma client/collection, enforces scalar-only metadata, upserts in batches of
100 by default, and exposes the query path used by retrieval.

Rules:

* persistent client at ``config.vector_store.persist_path`` (``data/chroma``);
* collection ``config.vector_store.collection`` (``groww_mf_faq``);
* cosine distance;
* upsert is idempotent by ``chunk_id`` (Chroma document ID);
* only scalar metadata values are stored; ``None`` is dropped and lists/maps
  are stringified.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import chromadb
import numpy as np
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import NotFoundError

DEFAULT_BATCH_SIZE = 100

# Metadata fields that retrieval needs. ``chunk_id`` is also the Chroma ID.
STORE_METADATA_FIELDS = (
    "chunk_id",
    "doc_id",
    "source_url",
    "source_title",
    "section",
    "content_type",
    "scraped_at",
)

_SCALAR_TYPES = (str, int, float, bool)


class StoreError(RuntimeError):
    """Raised when Chroma cannot be opened, written, or queried safely."""


def _stringify(value: Any) -> str:
    """Convert a non-scalar metadata value to a stable string."""

    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(_stringify(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def sanitize_metadata(metadata: Mapping[str, Any]) -> dict[str, str | int | float | bool]:
    """Return metadata with only Chroma-supported scalar values.

    ``None`` values are dropped. Lists, tuples, sets, and mappings are
    stringified. Non-finite floats are rendered as strings so Chroma does not
    reject them.
    """

    clean: dict[str, str | int | float | bool] = {}
    for raw_key, value in metadata.items():
        key = str(raw_key)
        if value is None:
            continue

        if isinstance(value, bool) or isinstance(value, (str, int)):
            clean[key] = value
        elif isinstance(value, float):
            clean[key] = value if math.isfinite(value) else str(value)
        elif isinstance(value, _SCALAR_TYPES):
            clean[key] = value
        else:
            clean[key] = _stringify(value)
    return clean


def chunk_metadata(metadata: Mapping[str, Any], *, chunk_id: str) -> dict:
    """Build the exact metadata payload stored for one chunk.

    The seven retrieval fields are required and must be non-empty strings.
    Extra fields (``text``, ``token_count``, ``embedding_model``, ...) are not
    persisted as Chroma metadata.
    """

    payload = sanitize_metadata(metadata)
    payload["chunk_id"] = chunk_id

    missing = [
        field
        for field in STORE_METADATA_FIELDS
        if field not in payload or payload[field] in ("", None)
    ]
    if missing:
        raise StoreError(
            f"Chunk {chunk_id!r} is missing metadata field(s): "
            f"{', '.join(missing)}"
        )

    non_string = [
        field
        for field in STORE_METADATA_FIELDS
        if not isinstance(payload[field], str)
    ]
    if non_string:
        raise StoreError(
            f"Chunk {chunk_id!r} metadata field(s) must be strings: "
            f"{', '.join(non_string)}"
        )

    return {field: payload[field] for field in STORE_METADATA_FIELDS}


class ChromaStore:
    """Thin, testable adapter around a persistent Chroma collection."""

    def __init__(
        self,
        persist_path: str | Path,
        collection: str,
        *,
        distance: str = "cosine",
        batch_size: int = DEFAULT_BATCH_SIZE,
        client: Any | None = None,
        embedding_function: Any | None = None,
    ):
        if distance not in {"cosine", "l2", "ip"}:
            raise StoreError(f"Unsupported Chroma distance: {distance!r}")
        if batch_size <= 0:
            raise StoreError("batch_size must be positive")

        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection
        self.distance = distance
        self.batch_size = batch_size
        self._embedding_function = embedding_function
        self._client = client or chromadb.PersistentClient(
            path=str(self.persist_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection: Any | None = None

    # ------------------------------------------------------------------
    # Collection lifecycle
    # ------------------------------------------------------------------

    def _check_existing_distance(self, collection: Any) -> None:
        existing = (collection.metadata or {}).get("hnsw:space")
        if existing and existing != self.distance:
            raise StoreError(
                f"Collection {self.collection_name!r} uses {existing!r} distance, "
                f"but config requires {self.distance!r}. Rebuild the collection."
            )

    @property
    def collection(self) -> Any:
        if self._collection is None:
            collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.distance},
                embedding_function=self._embedding_function,
            )
            self._check_existing_distance(collection)
            self._collection = collection
        return self._collection

    def rebuild(self) -> int:
        """Delete and recreate the collection with the configured distance."""

        try:
            self._client.delete_collection(self.collection_name)
        except NotFoundError:
            pass
        self._collection = self._client.create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": self.distance},
            embedding_function=self._embedding_function,
        )
        return self._collection.count()

    def count(self) -> int:
        """Return the number of stored chunks."""

        return int(self.collection.count())

    def assert_count(self, expected: int) -> None:
        actual = self.count()
        if actual != expected:
            raise StoreError(
                f"Collection {self.collection_name!r} has {actual} chunks, "
                f"expected {expected}. Re-run with --rebuild to remove stale data."
            )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert(
        self,
        ids: Sequence[str],
        embeddings: np.ndarray,
        documents: Sequence[str],
        metadatas: Sequence[Mapping[str, Any]],
    ) -> int:
        """Upsert aligned rows in batches, idempotently by chunk ID."""

        id_list = list(ids)
        document_list = list(documents)
        metadata_list = list(metadatas)

        if not id_list:
            raise StoreError("Refusing to upsert an empty batch")
        if len(id_list) != len(document_list):
            raise StoreError(
                "ids and documents must have the same length: "
                f"{len(id_list)} != {len(document_list)}"
            )
        if len(id_list) != len(metadata_list):
            raise StoreError(
                "ids and metadatas must have the same length: "
                f"{len(id_list)} != {len(metadata_list)}"
            )
        if len(set(id_list)) != len(id_list):
            raise StoreError("Duplicate chunk IDs in upsert payload")

        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim != 2:
            raise StoreError(
                f"embeddings must be a 2-D matrix, got shape {vectors.shape}"
            )
        if vectors.shape[0] != len(id_list):
            raise StoreError(
                f"Expected {len(id_list)} embedding rows, got {vectors.shape[0]}"
            )
        if vectors.shape[1] <= 0:
            raise StoreError("Embedding dimension must be positive")
        if not np.isfinite(vectors).all():
            raise StoreError("Embeddings contain non-finite values")

        prepared: list[dict[str, Any]] = []
        for index, (chunk_id, document, metadata) in enumerate(
            zip(id_list, document_list, metadata_list)
        ):
            if not isinstance(document, str) or not document.strip():
                raise StoreError(f"Chunk {chunk_id!r} has empty document text")
            prepared.append(
                {
                    "id": chunk_id,
                    "embedding": vectors[index],
                    "document": document,
                    "metadata": chunk_metadata(metadata, chunk_id=chunk_id),
                }
            )

        collection = self.collection
        for start in range(0, len(prepared), self.batch_size):
            batch = prepared[start : start + self.batch_size]
            collection.upsert(
                ids=[row["id"] for row in batch],
                embeddings=[row["embedding"].tolist() for row in batch],
                documents=[row["document"] for row in batch],
                metadatas=[row["metadata"] for row in batch],
            )

        return len(prepared)

    def delete(self, ids: Iterable[str]) -> None:
        """Delete chunks by ID; missing IDs are ignored by Chroma."""

        id_list = list(ids)
        if id_list:
            self.collection.delete(ids=id_list)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the nearest chunks for one query embedding.

        ``score`` is cosine similarity (``1 - distance``) and is only
        meaningful when both corpus and query vectors are normalized.
        """

        vector = self._validate_query_embedding(query_embedding)
        if top_k <= 0:
            raise StoreError("top_k must be positive")

        collection = self.collection
        total = collection.count()
        if total == 0:
            return []

        result = collection.query(
            query_embeddings=vector.tolist(),
            n_results=min(top_k, int(total)),
            where=dict(where) if where else None,
            include=["documents", "metadatas", "distances"],
        )
        return self._hits_from_result(result)

    def search_facts(
        self,
        query_embedding: np.ndarray,
        *,
        regex: str,
        doc_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search chunks whose text matches ``regex`` (case-insensitive).

        Vector search alone can miss a small table row such as
        ``Expense ratio | 0.75%``. This filtered query keeps retrieval in the
        same collection while guaranteeing that a requested fact is available
        to the sufficiency check when the corpus contains it.
        """

        if not regex:
            raise StoreError("regex must not be empty")
        if top_k <= 0:
            raise StoreError("top_k must be positive")

        vector = self._validate_query_embedding(query_embedding)
        collection = self.collection
        total = collection.count()
        if total == 0:
            return []

        result = collection.query(
            query_embeddings=vector.tolist(),
            n_results=min(top_k, int(total)),
            where={"doc_id": doc_id} if doc_id else None,
            where_document={"$regex": regex},
            include=["documents", "metadatas", "distances"],
        )
        return self._hits_from_result(result)

    @staticmethod
    def _validate_query_embedding(query_embedding: np.ndarray) -> np.ndarray:
        vector = np.asarray(query_embedding, dtype=np.float32)
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        if vector.ndim != 2 or vector.shape[0] != 1:
            raise StoreError(
                f"query_embedding must be one vector, got shape {vector.shape}"
            )
        if not np.isfinite(vector).all():
            raise StoreError("query_embedding contains non-finite values")
        return vector

    @staticmethod
    def _hits_from_result(result: Mapping[str, Any]) -> list[dict[str, Any]]:
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[dict[str, Any]] = []
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances
        ):
            numeric_distance = float(distance)
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "text": document,
                    "metadata": dict(metadata or {}),
                    "distance": numeric_distance,
                    "score": 1.0 - numeric_distance,
                }
            )
        return hits
