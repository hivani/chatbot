"""Command-line pipeline for the ingest stages.

Phase 2 exposes the ``load`` stage. Only the URLs listed in ``sources.csv``
are fetched; links and internal documents found on those pages are ignored:

    python -m src.ingest.pipeline --stage load

Phase 3 exposes the ``load-docs`` stage. It loads and validates
``data/raw/*.json`` before the chunker is allowed to read them:

    python -m src.ingest.pipeline --stage load-docs

Phase 4 exposes the ``chunk`` stage. It validates the raw documents, splits
them into self-describing chunks, and writes ``data/chunks/chunks.jsonl``:

    python -m src.ingest.pipeline --stage chunk

Phase 5 exposes the ``embed`` stage. It embeds the chunks with the configured
sentence-transformer and writes ``data/embeddings/embeddings.npz`` plus
``data/embeddings/metadata.jsonl``:

    python -m src.ingest.pipeline --stage embed

Phase 6 exposes the ``index`` stage. It loads the chunks/embeddings, upserts
them into Chroma (``data/chroma``, collection ``groww_mf_faq``), and asserts
the collection count matches the chunk count:

    python -m src.ingest.pipeline --stage index

Use ``--stage all --rebuild`` to run ``load -> load-docs -> chunk -> embed ->
index`` from scratch and recreate the collection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from src.config import ConfigError, load_settings
from src.ingest.chunker import (
    ChunkError,
    HuggingFaceTokenCounter,
    chunk_documents,
    read_chunks,
    write_chunks,
)
from src.ingest.loader import (
    MANIFEST_FILENAME,
    MIN_SOURCES,
    DocumentError,
    SourceError,
    load_all,
    load_raw_documents,
    load_sources,
)
from src.rag.embedder import (
    EmbeddingError,
    SentenceTransformerEmbedder,
    embed_chunks,
    read_embeddings,
    write_embeddings,
)
from src.rag.store import ChromaStore, StoreError


def run_load(
    *,
    sources_path: str | Path | None = None,
    raw_dir: str | Path | None = None,
    only: list[str] | None = None,
) -> int:
    """Scrape every source into ``data/raw`` and print a summary."""

    settings = load_settings()
    source_file = Path(sources_path) if sources_path else settings.paths.sources
    output_dir = Path(raw_dir) if raw_dir else settings.paths.raw_dir

    specs = load_sources(source_file)
    if only:
        wanted = set(only)
        selected = [spec for spec in specs if spec.id in wanted]
        missing = wanted - {spec.id for spec in selected}
        if missing:
            raise SourceError(
                f"Unknown source id(s): {', '.join(sorted(missing))}. "
                f"Available ids: {', '.join(spec.id for spec in specs)}"
            )
        specs = selected

    minimum_required = 1 if only else MIN_SOURCES
    manifest = load_all(
        specs,
        output_dir,
        sources_file=source_file,
        minimum_required=minimum_required,
    )

    print(
        f"Ingest {manifest.status}: {manifest.succeeded}/{manifest.total} sources "
        f"succeeded, {manifest.failed} failed"
    )
    print(f"Raw documents: {output_dir}")
    print(f"Manifest: {output_dir / 'ingest_manifest.json'}")

    for result in manifest.results:
        if result.status == "failed":
            print(f"  FAILED {result.doc_id}: {result.error}", file=sys.stderr)

    return 0 if manifest.status == "success" else 1


def run_load_docs(
    *,
    sources_path: str | Path | None = None,
    raw_dir: str | Path | None = None,
) -> int:
    """Load and validate ``data/raw`` before chunking."""

    settings = load_settings()
    source_file = Path(sources_path) if sources_path else settings.paths.sources
    raw_path = Path(raw_dir) if raw_dir else settings.paths.raw_dir

    specs = load_sources(source_file)
    documents = load_raw_documents(raw_path, specs)

    total_chars = sum(len(document.text) for document in documents)
    manifest_path = raw_path / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    succeeded = manifest.get("succeeded")

    print(f"Loaded documents: {len(documents)}")
    print(f"Total characters: {total_chars}")
    print(f"Raw documents: {raw_path}")
    print(f"Manifest succeeded: {succeeded}")

    if succeeded != len(documents):
        print(
            "warning: loaded document count does not match manifest succeeded count",
            file=sys.stderr,
        )

    return 0


def run_chunk(
    *,
    sources_path: str | Path | None = None,
    raw_dir: str | Path | None = None,
    chunks_file: str | Path | None = None,
) -> int:
    """Validate raw documents, chunk them, and write ``chunks.jsonl``."""

    settings = load_settings()
    source_file = Path(sources_path) if sources_path else settings.paths.sources
    raw_path = Path(raw_dir) if raw_dir else settings.paths.raw_dir
    output_file = (
        Path(chunks_file) if chunks_file else settings.paths.chunks_file
    )

    specs = load_sources(source_file)
    documents = load_raw_documents(raw_path, specs)

    token_counter = HuggingFaceTokenCounter(settings.embedding.model)
    chunks = chunk_documents(
        documents,
        token_counter,
        chunk_size=settings.chunking.chunk_size,
        chunk_overlap=settings.chunking.chunk_overlap,
        max_seq_length=settings.embedding.max_seq_length,
    )
    write_chunks(chunks, output_file)

    token_counts = [chunk.token_count for chunk in chunks]
    print(f"Chunked documents: {len(documents)}")
    print(f"Chunks written: {len(chunks)}")
    if token_counts:
        print(
            f"Token range: {min(token_counts)}-{max(token_counts)} "
            f"(max_seq_length={settings.embedding.max_seq_length})"
        )
    print(f"Chunks file: {output_file}")

    return 0


def run_embed(
    *,
    sources_path: str | Path | None = None,
    raw_dir: str | Path | None = None,
    chunks_file: str | Path | None = None,
    embeddings_dir: str | Path | None = None,
) -> int:
    """Read chunks, embed them, and write embeddings + metadata."""

    settings = load_settings()
    source_file = Path(sources_path) if sources_path else settings.paths.sources
    raw_path = Path(raw_dir) if raw_dir else settings.paths.raw_dir
    chunks_path = Path(chunks_file) if chunks_file else settings.paths.chunks_file
    output_dir = (
        Path(embeddings_dir) if embeddings_dir else settings.paths.embeddings_dir
    )

    # Ensure raw documents/manifest are validated before reading chunks, and
    # that the sources CSV is still valid for this run.
    specs = load_sources(source_file)
    load_raw_documents(raw_path, specs)

    chunks = read_chunks(chunks_path)
    embedder = SentenceTransformerEmbedder(
        settings.embedding.model,
        max_seq_length=settings.embedding.max_seq_length,
    )
    ids, vectors, metadata = embed_chunks(
        chunks,
        embedder,
        max_seq_length=settings.embedding.max_seq_length,
        batch_size=settings.embedding.batch_size,
        normalize=settings.embedding.normalize,
    )
    npz_path, metadata_path = write_embeddings(ids, vectors, metadata, output_dir)

    norm = float(np.linalg.norm(vectors[0])) if len(vectors) else 0.0
    print(f"Embedded chunks: {len(chunks)}")
    print(f"Shape: {vectors.shape}, dtype: {vectors.dtype}")
    print(f"Norm of first vector: {norm}")
    print(f"Embeddings: {npz_path}")
    print(f"Metadata: {metadata_path}")

    return 0


def run_index(
    *,
    chunks_file: str | Path | None = None,
    embeddings_dir: str | Path | None = None,
    persist_path: str | Path | None = None,
    collection: str | None = None,
    rebuild: bool = False,
) -> int:
    """Upsert chunk embeddings into Chroma and verify the stored count."""

    settings = load_settings()
    chunks_path = Path(chunks_file) if chunks_file else settings.paths.chunks_file
    embeddings_path = (
        Path(embeddings_dir) if embeddings_dir else settings.paths.embeddings_dir
    )
    chroma_path = (
        Path(persist_path)
        if persist_path
        else settings.vector_store.persist_path
    )
    collection_name = collection or settings.vector_store.collection

    chunks = read_chunks(chunks_path)
    ids, vectors, metadata = read_embeddings(embeddings_path)

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if ids != chunk_ids:
        raise StoreError(
            "Embeddings do not align with chunks.jsonl. Re-run the embed stage."
        )
    for chunk, row in zip(chunks, metadata):
        if row.get("text") != chunk.text:
            raise StoreError(
                f"Embedding metadata for {chunk.chunk_id!r} is stale. "
                "Re-run the embed stage."
            )

    store = ChromaStore(
        chroma_path,
        collection_name,
        distance=settings.vector_store.distance,
    )
    if rebuild:
        store.rebuild()

    written = store.upsert(
        ids,
        vectors,
        [row["text"] for row in metadata],
        metadata,
    )
    store.assert_count(len(chunks))

    print(f"Collection: {collection_name}")
    print(f"Persist path: {chroma_path}")
    print(f"Distance: {settings.vector_store.distance}")
    print(f"Upserted: {written}")
    print(f"Collection count: {store.count()}")
    if rebuild:
        print("Collection rebuilt: yes")

    return 0


def run_all(
    *,
    sources_path: str | Path | None = None,
    raw_dir: str | Path | None = None,
    chunks_file: str | Path | None = None,
    embeddings_dir: str | Path | None = None,
    persist_path: str | Path | None = None,
    collection: str | None = None,
    rebuild: bool = False,
) -> int:
    """Run the full ingest chain: load -> load-docs -> chunk -> embed -> index."""

    status = run_load(sources_path=sources_path, raw_dir=raw_dir)
    if status != 0:
        return status
    run_load_docs(sources_path=sources_path, raw_dir=raw_dir)
    run_chunk(
        sources_path=sources_path,
        raw_dir=raw_dir,
        chunks_file=chunks_file,
    )
    run_embed(
        sources_path=sources_path,
        raw_dir=raw_dir,
        chunks_file=chunks_file,
        embeddings_dir=embeddings_dir,
    )
    return run_index(
        chunks_file=chunks_file,
        embeddings_dir=embeddings_dir,
        persist_path=persist_path,
        collection=collection,
        rebuild=rebuild,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingest.pipeline",
        description="Run ingest pipeline stages for the Groww mutual fund FAQ corpus.",
    )
    parser.add_argument(
        "--stage",
        choices=("load", "load-docs", "chunk", "embed", "index", "all"),
        default="load",
        help="Pipeline stage to run (default: load).",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=None,
        help="Override the sources CSV path (default: config.paths.sources).",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Override the raw document directory (default: config.paths.raw_dir).",
    )
    parser.add_argument(
        "--chunks-file",
        type=Path,
        default=None,
        help="Override the chunks JSONL path (default: config.paths.chunks_file).",
    )
    parser.add_argument(
        "--embeddings-dir",
        type=Path,
        default=None,
        help="Override the embeddings output directory (default: config.paths.embeddings_dir).",
    )
    parser.add_argument(
        "--chroma-path",
        type=Path,
        default=None,
        help="Override the Chroma persist directory (default: config.vector_store.persist_path).",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Override the Chroma collection name (default: config.vector_store.collection).",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Recreate the Chroma collection before indexing (index/all stages).",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="DOC_ID",
        help="Load only the given source id (load stage only). Repeat for multiple ids.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.stage == "load":
            return run_load(
                sources_path=args.sources,
                raw_dir=args.raw_dir,
                only=args.only,
            )
        if args.stage == "load-docs":
            if args.only:
                print(
                    "error: --only is only supported with --stage load",
                    file=sys.stderr,
                )
                return 2
            return run_load_docs(
                sources_path=args.sources,
                raw_dir=args.raw_dir,
            )
        if args.stage == "chunk":
            if args.only:
                print(
                    "error: --only is only supported with --stage load",
                    file=sys.stderr,
                )
                return 2
            return run_chunk(
                sources_path=args.sources,
                raw_dir=args.raw_dir,
                chunks_file=args.chunks_file,
            )
        if args.stage == "embed":
            if args.only:
                print(
                    "error: --only is only supported with --stage load",
                    file=sys.stderr,
                )
                return 2
            return run_embed(
                sources_path=args.sources,
                raw_dir=args.raw_dir,
                chunks_file=args.chunks_file,
                embeddings_dir=args.embeddings_dir,
            )
        if args.stage == "index":
            if args.only:
                print(
                    "error: --only is only supported with --stage load",
                    file=sys.stderr,
                )
                return 2
            return run_index(
                chunks_file=args.chunks_file,
                embeddings_dir=args.embeddings_dir,
                persist_path=args.chroma_path,
                collection=args.collection,
                rebuild=args.rebuild,
            )
        if args.stage == "all":
            if args.only:
                print(
                    "error: --only is only supported with --stage load",
                    file=sys.stderr,
                )
                return 2
            return run_all(
                sources_path=args.sources,
                raw_dir=args.raw_dir,
                chunks_file=args.chunks_file,
                embeddings_dir=args.embeddings_dir,
                persist_path=args.chroma_path,
                collection=args.collection,
                rebuild=args.rebuild,
            )
    except (
        ConfigError,
        ChunkError,
        DocumentError,
        EmbeddingError,
        SourceError,
        StoreError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
