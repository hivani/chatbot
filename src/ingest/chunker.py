"""Split validated raw documents into self-describing retrieval chunks.

Phase 4 of the ingest pipeline. The chunker never reads ``data/raw`` directly;
it receives the documents validated by :func:`src.ingest.loader.load_raw_documents`.

Rules implemented here:

* split prose at headings, then at sentence boundaries;
* keep tables intact, and repeat a table's header row when a table must be
  split into batches;
* never separate a table row from its header or scheme name;
* prefix every chunk with ``"<scheme/title> — <section>. "``;
* use ``chunk_id = "<doc_id>::<section-slug>::<index>"``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from src.ingest.loader import RawDocument, content_hash, normalize_text

DEFAULT_CHUNK_SIZE = 220
DEFAULT_CHUNK_OVERLAP = 40
DEFAULT_MAX_SEQ_LENGTH = 256

# A table may stay intact slightly above chunk_size, but never above the
# embedding model's hard limit.
TABLE_TOKEN_SLACK = 55

# Split after terminal punctuation only when the next sentence starts with a
# capital letter, digit, currency symbol, or opening quote/bracket. Decimals
# such as "1.20%" and "₹1,434.92" have no following space, so they stay intact.
SENTENCE_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z0-9₹\"'(\[])", flags=re.UNICODE
)
SLUG_RE = re.compile(r"[^a-z0-9]+")
CHUNK_ID_INDEX_WIDTH = 3

_HEADER_LABELS = {
    "amount",
    "assets",
    "description",
    "detail",
    "details",
    "document",
    "feature",
    "fund",
    "link",
    "name",
    "parameter",
    "particulars",
    "scheme",
    "type",
    "value",
}


class ChunkError(RuntimeError):
    """Raised when documents cannot be chunked safely."""


class TokenCounter(Protocol):
    """Minimal tokenizer interface used by the chunker."""

    def count(self, text: str) -> int:
        """Return the number of model tokens in ``text``."""


class HuggingFaceTokenCounter:
    """Count tokens with the embedding model's own tokenizer."""

    def __init__(self, model_name: str):
        try:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        except Exception as exc:  # noqa: BLE001 - surface a clear chunking error
            raise ChunkError(
                f"Could not load the tokenizer for {model_name!r}: {exc}"
            ) from exc

    def count(self, text: str) -> int:
        encoded = self._tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            verbose=False,
        )
        return len(encoded["input_ids"])


class WhitespaceTokenCounter:
    """Deterministic word counter for offline tests and diagnostics.

    The ingest pipeline uses :class:`HuggingFaceTokenCounter`; this counter is
    intentionally not a silent production fallback.
    """

    def count(self, text: str) -> int:
        return len(text.split())


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source_url: str
    source_title: str
    scraped_at: str
    section: str
    content_type: str
    text: str
    token_count: int
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "scraped_at": self.scraped_at,
            "section": self.section,
            "content_type": self.content_type,
            "text": self.text,
            "token_count": self.token_count,
            "content_hash": self.content_hash,
        }


@dataclass
class _Section:
    name: str
    blocks: list[dict]


# ---------------------------------------------------------------------------
# Text and identifier helpers
# ---------------------------------------------------------------------------


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking decimals or currency."""

    cleaned = normalize_text(text)
    if not cleaned:
        return []
    return [part.strip() for part in SENTENCE_RE.split(cleaned) if part.strip()]


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.casefold()).strip("-")
    return slug or "section"


def _same_scheme_name(left: str, right: str) -> bool:
    return normalize_text(left).casefold() == normalize_text(right).casefold()


def _section_name(heading: str, document_title: str) -> str:
    if _same_scheme_name(heading, document_title):
        return "Overview"
    return normalize_text(heading) or "Overview"


def _prose_prefix(title: str, section: str) -> str:
    return f"{title} — {section}. "


def _table_prefix(title: str, section: str) -> str:
    return f"{title} — {section} (table). "


def _heading_text(block: dict) -> str:
    return normalize_text(block.get("text"))


def _block_text(block: dict) -> str:
    kind = block.get("kind")
    if kind == "paragraph":
        return normalize_text(block.get("text"))
    if kind == "list":
        return "\n".join(
            normalize_text(item)
            for item in block.get("items", [])
            if normalize_text(item)
        )
    return ""


# ---------------------------------------------------------------------------
# Sectioning
# ---------------------------------------------------------------------------


def _split_sections(document: RawDocument) -> list[_Section]:
    sections: list[_Section] = []
    current = _Section(name="Overview", blocks=[])

    for block in document.blocks:
        kind = block.get("kind")
        if kind == "heading":
            heading = _heading_text(block)
            if not heading:
                continue
            if current.blocks:
                sections.append(current)
            current = _Section(
                name=_section_name(heading, document.title),
                blocks=[],
            )
            continue

        if kind not in {"paragraph", "list", "table"}:
            continue
        if kind == "table":
            if not block.get("rows"):
                continue
        elif not _block_text(block):
            continue
        current.blocks.append(block)

    if current.blocks:
        sections.append(current)
    return sections


# ---------------------------------------------------------------------------
# Prose chunking
# ---------------------------------------------------------------------------


def _overlap_tail(
    units: Sequence[str],
    overlap: int,
    token_counter: TokenCounter,
) -> list[str]:
    if overlap <= 0:
        return []

    tail: list[str] = []
    for unit in reversed(units):
        candidate = [unit, *tail]
        if token_counter.count("\n".join(candidate)) <= overlap:
            tail = candidate
        else:
            break
    return tail


def _split_by_words(
    text: str,
    prefix: str,
    chunk_size: int,
    token_counter: TokenCounter,
) -> list[str]:
    words = text.split()
    if len(words) <= 1:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and token_counter.count(prefix + candidate) > chunk_size:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _fit_unit(
    unit: str,
    prefix: str,
    chunk_size: int,
    token_counter: TokenCounter,
) -> list[str]:
    if token_counter.count(prefix + unit) <= chunk_size:
        return [unit]

    sentences = split_sentences(unit)
    if len(sentences) > 1:
        return _pack_units(
            sentences,
            prefix,
            chunk_size=chunk_size,
            overlap=0,
            token_counter=token_counter,
        )

    return _split_by_words(unit, prefix, chunk_size, token_counter)


def _pack_units(
    units: Sequence[str],
    prefix: str,
    *,
    chunk_size: int,
    overlap: int,
    token_counter: TokenCounter,
) -> list[str]:
    if not units:
        return []

    chunks: list[str] = []
    current: list[str] = []

    for unit in units:
        for piece in _fit_unit(unit, prefix, chunk_size, token_counter):
            while current and (
                token_counter.count(prefix + "\n".join([*current, piece]))
                > chunk_size
            ):
                chunks.append("\n".join(current))
                current = _overlap_tail(current, overlap, token_counter)
                if current and (
                    token_counter.count(prefix + "\n".join([*current, piece]))
                    > chunk_size
                ):
                    # The overlap itself does not leave room for the next unit.
                    current = []

            if not current and token_counter.count(prefix + piece) > chunk_size:
                # An indivisible unit longer than the budget. Emit it and let
                # the max_seq_length check decide whether the corpus is usable.
                chunks.append(piece)
                continue

            current.append(piece)

    if current:
        chunks.append("\n".join(current))
    return chunks


# ---------------------------------------------------------------------------
# Table chunking
# ---------------------------------------------------------------------------


def _looks_like_header(rows: Sequence[Sequence[str]]) -> bool:
    if len(rows) < 2 or len(rows[0]) < 2:
        return False
    first = [normalize_text(cell).casefold().rstrip(":") for cell in rows[0]]
    if len(first) >= 3:
        return True
    return bool(set(first) & _HEADER_LABELS)


def _render_table(header: Sequence[str] | None, rows: Sequence[str]) -> str:
    lines: list[str] = []
    if header:
        lines.append(" | ".join(header))
    lines.extend(rows)
    return "\n".join(lines)


def _pack_table(
    rows: Sequence[Sequence[str]],
    prefix: str,
    *,
    chunk_size: int,
    max_tokens: int,
    token_counter: TokenCounter,
) -> list[str]:
    normalized = [
        [normalize_text(cell) for cell in row] for row in rows if any(row)
    ]
    if not normalized:
        return []

    header: list[str] | None = None
    data = list(normalized)
    if _looks_like_header(normalized):
        header = normalized[0]
        data = normalized[1:]

    rendered_rows = [" | ".join(row) for row in data]
    whole = _render_table(header, rendered_rows)

    # Keep a table intact whenever it fits the (slightly relaxed) table budget.
    if token_counter.count(prefix + whole) <= max_tokens:
        return [whole]

    batches: list[str] = []
    current: list[str] = []
    for row in rendered_rows:
        if not current:
            current = [row]
            continue

        candidate = [*current, row]
        if token_counter.count(prefix + _render_table(header, candidate)) <= chunk_size:
            current = candidate
        else:
            batches.append(_render_table(header, current))
            current = [row]
    if current:
        batches.append(_render_table(header, current))

    return batches


# ---------------------------------------------------------------------------
# Document chunking
# ---------------------------------------------------------------------------


def _section_chunks(
    document: RawDocument,
    section: _Section,
    *,
    chunk_size: int,
    chunk_overlap: int,
    max_seq_length: int,
    token_counter: TokenCounter,
) -> list[tuple[str, str]]:
    """Return ``(body, content_type)`` pairs for one section."""

    results: list[tuple[str, str]] = []
    prose_prefix = _prose_prefix(document.title, section.name)
    table_prefix = _table_prefix(document.title, section.name)
    table_limit = min(chunk_size + TABLE_TOKEN_SLACK, max_seq_length)

    prose_units: list[str] = []
    prose_types: list[str] = []

    def flush_prose() -> None:
        nonlocal prose_units, prose_types
        if not prose_units:
            return
        content_type = "list" if all(kind == "list" for kind in prose_types) else "paragraph"
        for body in _pack_units(
            prose_units,
            prose_prefix,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
            token_counter=token_counter,
        ):
            results.append((body, content_type))
        prose_units = []
        prose_types = []

    for block in section.blocks:
        kind = block.get("kind")
        if kind == "table":
            flush_prose()
            for body in _pack_table(
                block.get("rows", []),
                table_prefix,
                chunk_size=chunk_size,
                max_tokens=table_limit,
                token_counter=token_counter,
            ):
                results.append((body, "table"))
            continue

        if kind == "paragraph":
            prose_units.extend(split_sentences(block.get("text", "")))
            prose_types.append("paragraph")
            continue

        if kind == "list":
            for item in block.get("items", []):
                item = normalize_text(item)
                if item:
                    prose_units.append(item)
            prose_types.append("list")

    flush_prose()
    return results


def _chunk_document(
    document: RawDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
    max_seq_length: int,
    token_counter: TokenCounter,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    section_counts: dict[str, int] = {}

    for section in _split_sections(document):
        slug = slugify(section.name)
        for body, content_type in _section_chunks(
            document,
            section,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_seq_length=max_seq_length,
            token_counter=token_counter,
        ):
            prefix = (
                _table_prefix(document.title, section.name)
                if content_type == "table"
                else _prose_prefix(document.title, section.name)
            )
            text = prefix + body
            index = section_counts.get(slug, 0) + 1
            section_counts[slug] = index
            chunks.append(
                Chunk(
                    chunk_id=(
                        f"{document.doc_id}::{slug}::"
                        f"{index:0{CHUNK_ID_INDEX_WIDTH}d}"
                    ),
                    doc_id=document.doc_id,
                    source_url=document.url,
                    source_title=document.title,
                    scraped_at=document.scraped_at,
                    section=section.name,
                    content_type=content_type,
                    text=text,
                    token_count=token_counter.count(text),
                    content_hash=content_hash(text),
                )
            )

    return chunks


def chunk_documents(
    documents: Sequence[RawDocument],
    token_counter: TokenCounter,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_seq_length: int = DEFAULT_MAX_SEQ_LENGTH,
) -> list[Chunk]:
    """Chunk validated documents into deterministic, self-describing units.

    Raises:
        ChunkError: if settings are invalid, chunk IDs collide, or a chunk
            exceeds ``max_seq_length``.
    """

    if chunk_size <= 0:
        raise ChunkError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ChunkError("chunk_overlap must be >= 0 and smaller than chunk_size")
    if max_seq_length <= 0 or chunk_size > max_seq_length:
        raise ChunkError("chunk_size must be <= max_seq_length")

    chunks: list[Chunk] = []
    seen_ids: set[str] = set()

    for document in sorted(documents, key=lambda item: item.doc_id):
        for chunk in _chunk_document(
            document,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_seq_length=max_seq_length,
            token_counter=token_counter,
        ):
            if chunk.chunk_id in seen_ids:
                raise ChunkError(f"Duplicate chunk_id: {chunk.chunk_id}")
            if chunk.token_count > max_seq_length:
                raise ChunkError(
                    f"Chunk {chunk.chunk_id} has {chunk.token_count} tokens, "
                    f"above max_seq_length={max_seq_length}"
                )
            seen_ids.add(chunk.chunk_id)
            chunks.append(chunk)

    return chunks


def write_chunks(chunks: Sequence[Chunk], path: str | Path) -> Path:
    """Write chunks as JSONL, atomically replacing the target file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(
                json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n"
            )
    temporary.replace(target)
    return target


CHUNK_FIELDS = (
    "chunk_id",
    "doc_id",
    "source_url",
    "source_title",
    "scraped_at",
    "section",
    "content_type",
    "text",
    "token_count",
    "content_hash",
)


def read_chunks(path: str | Path) -> list[Chunk]:
    """Read and validate ``chunks.jsonl`` for the embedding stage.

    The file is rejected if a line is not a JSON object, a required field is
    missing or mistyped, a chunk ID repeats, or a chunk's content hash no
    longer matches its text.
    """

    target = Path(path)
    if not target.exists():
        raise ChunkError(f"Chunks file not found: {target}")

    chunks: list[Chunk] = []
    seen_ids: set[str] = set()

    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ChunkError(f"Could not read chunks file {target}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ChunkError(
                f"{target}:{line_number} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ChunkError(f"{target}:{line_number} must be a JSON object")

        missing = [field for field in CHUNK_FIELDS if field not in payload]
        if missing:
            raise ChunkError(
                f"{target}:{line_number} is missing field(s): {', '.join(missing)}"
            )

        for field in CHUNK_FIELDS:
            if field == "token_count":
                continue
            if not isinstance(payload[field], str) or not payload[field].strip():
                raise ChunkError(
                    f"{target}:{line_number} field {field!r} must be a non-empty string"
                )

        token_count = payload["token_count"]
        if (
            not isinstance(token_count, int)
            or isinstance(token_count, bool)
            or token_count <= 0
        ):
            raise ChunkError(
                f"{target}:{line_number} field 'token_count' must be a positive integer"
            )

        actual_hash = content_hash(payload["text"])
        if actual_hash != payload["content_hash"]:
            raise ChunkError(
                f"{target}:{line_number} content hash mismatch: stored "
                f"{payload['content_hash']!r}, recomputed {actual_hash!r}"
            )

        if payload["chunk_id"] in seen_ids:
            raise ChunkError(
                f"{target}:{line_number} repeats chunk_id {payload['chunk_id']!r}"
            )
        seen_ids.add(payload["chunk_id"])

        chunks.append(Chunk(**{field: payload[field] for field in CHUNK_FIELDS}))

    if not chunks:
        raise ChunkError(f"Chunks file has no chunks: {target}")
    return chunks
