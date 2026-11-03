import json

import pytest

from src.ingest.chunker import (
    ChunkError,
    WhitespaceTokenCounter,
    chunk_documents,
    read_chunks,
    slugify,
    split_sentences,
    write_chunks,
)
from src.ingest.loader import RawDocument, content_hash, utc_now_iso

DOC_URL = "https://groww.in/mutual-funds/test-fund"


def _doc(
    *,
    doc_id: str = "test-doc",
    title: str = "Test Fund",
    blocks: list[dict] | None = None,
) -> RawDocument:
    text = "Test Fund body"
    return RawDocument(
        doc_id=doc_id,
        url=DOC_URL,
        title=title,
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


def _chunks(document: RawDocument, **kwargs):
    defaults = {
        "chunk_size": 50,
        "chunk_overlap": 0,
        "max_seq_length": 60,
    }
    defaults.update(kwargs)
    return chunk_documents(
        [document],
        WhitespaceTokenCounter(),
        **defaults,
    )


def _assert_valid_chunk_ids(chunks):
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(ids) == len(set(ids))
    for chunk in chunks:
        assert chunk.chunk_id.startswith(f"{chunk.doc_id}::")
        assert chunk.chunk_id.split("::")[-1].isdigit()


# ---------------------------------------------------------------------------
# Prose
# ---------------------------------------------------------------------------


def test_chunk_prefix_section_and_metadata():
    document = _doc(
        blocks=[
            {"kind": "heading", "level": 1, "text": "Test Fund"},
            {"kind": "heading", "level": 2, "text": "Fund details"},
            {
                "kind": "paragraph",
                "text": "Expense ratio is 1.20 percent. Exit load is Nil.",
            },
        ]
    )

    chunks = _chunks(document)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text.startswith("Test Fund — Fund details. ")
    assert chunk.section == "Fund details"
    assert chunk.content_type == "paragraph"
    assert chunk.source_url == DOC_URL
    assert chunk.source_title == "Test Fund"
    assert chunk.scraped_at == document.scraped_at
    assert chunk.chunk_id == "test-doc::fund-details::001"
    assert chunk.token_count == len(chunk.text.split())
    assert chunk.content_hash == content_hash(chunk.text)


def test_prose_splits_on_sentence_boundaries_with_overlap():
    document = _doc(
        blocks=[
            {"kind": "heading", "level": 2, "text": "Facts"},
            {
                "kind": "paragraph",
                "text": (
                    "Alpha beta gamma. Delta epsilon zeta. Eta theta iota."
                ),
            },
        ]
    )

    chunks = _chunks(document, chunk_size=12, chunk_overlap=3)

    assert len(chunks) == 2
    assert chunks[0].text.endswith("Delta epsilon zeta.")
    assert "Delta epsilon zeta." in chunks[1].text
    assert "Eta theta iota." in chunks[1].text
    assert all(chunk.token_count <= 12 for chunk in chunks)
    assert chunks[0].chunk_id == "test-doc::facts::001"
    assert chunks[1].chunk_id == "test-doc::facts::002"
    _assert_valid_chunk_ids(chunks)


def test_heading_equal_to_title_becomes_overview_section():
    document = _doc(
        blocks=[
            {"kind": "heading", "level": 1, "text": "Test Fund"},
            {"kind": "paragraph", "text": "A facts-only overview sentence."},
        ]
    )

    chunks = _chunks(document)

    assert len(chunks) == 1
    assert chunks[0].section == "Overview"
    assert chunks[0].text.startswith("Test Fund — Overview. ")


def test_headings_create_separate_sections_and_empty_sections_are_skipped():
    document = _doc(
        blocks=[
            {"kind": "heading", "level": 2, "text": "Facts"},
            {"kind": "paragraph", "text": "Expense ratio is 1.20 percent."},
            {"kind": "heading", "level": 3, "text": "Empty section"},
            {"kind": "heading", "level": 2, "text": "Charges"},
            {"kind": "paragraph", "text": "Exit load is Nil."},
        ]
    )

    chunks = _chunks(document)

    assert [chunk.section for chunk in chunks] == ["Facts", "Charges"]
    assert [chunk.chunk_id for chunk in chunks] == [
        "test-doc::facts::001",
        "test-doc::charges::001",
    ]
    assert all("Empty section" not in chunk.text for chunk in chunks)


def test_lists_are_chunked_as_list_content():
    document = _doc(
        blocks=[
            {"kind": "heading", "level": 2, "text": "Steps"},
            {"kind": "list", "items": ["Open the app.", "Open the statement."]},
        ]
    )

    chunks = _chunks(document, chunk_size=30)

    assert len(chunks) == 1
    assert chunks[0].content_type == "list"
    assert "Open the app." in chunks[0].text
    assert "Open the statement." in chunks[0].text


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _table_document() -> RawDocument:
    rows = [["Name", "Assets", "Weight"]]
    rows.extend([[f"Row{i}", f"{i}%", f"{i}00"] for i in range(1, 21)])
    return _doc(
        blocks=[
            {"kind": "heading", "level": 2, "text": "Holdings"},
            {"kind": "table", "rows": rows},
        ]
    )


def test_large_table_splits_into_batches_with_repeated_header():
    chunks = _chunks(_table_document(), chunk_size=25, max_seq_length=256)

    assert len(chunks) > 1
    assert all(chunk.content_type == "table" for chunk in chunks)
    assert all(chunk.text.startswith("Test Fund — Holdings (table). ") for chunk in chunks)
    assert all("Name | Assets | Weight" in chunk.text for chunk in chunks)

    row_lines = [f"Row{i} | {i}% | {i}00" for i in range(1, 21)]
    for row_line in row_lines:
        matches = [chunk for chunk in chunks if row_line in chunk.text]
        assert len(matches) == 1, row_line


def test_small_table_stays_intact():
    document = _doc(
        blocks=[
            {"kind": "heading", "level": 2, "text": "Facts"},
            {
                "kind": "table",
                "rows": [
                    ["Expense ratio", "1.20%"],
                    ["Exit load", "Nil"],
                ],
            },
        ]
    )

    chunks = _chunks(document, chunk_size=60)

    assert len(chunks) == 1
    assert chunks[0].content_type == "table"
    assert "Expense ratio | 1.20%" in chunks[0].text
    assert "Exit load | Nil" in chunks[0].text


def test_table_row_above_max_seq_length_raises():
    document = _doc(
        title="T",
        blocks=[
            {"kind": "heading", "level": 2, "text": "Facts"},
            {
                "kind": "table",
                "rows": [
                    [f"Cell{i}" for i in range(10)],
                ],
            },
        ],
    )

    with pytest.raises(ChunkError, match="above max_seq_length"):
        _chunks(document, chunk_size=8, max_seq_length=10)


# ---------------------------------------------------------------------------
# Identifiers and persistence
# ---------------------------------------------------------------------------


def test_slugify_and_sentence_helpers():
    assert slugify("Fund details") == "fund-details"
    assert slugify("  ELSS / Lock-in! ") == "elss-lock-in"
    assert slugify("") == "section"
    assert split_sentences("Rate is 1.20%. Exit load is Nil.") == [
        "Rate is 1.20%.",
        "Exit load is Nil.",
    ]


def test_write_chunks_writes_one_json_object_per_line(tmp_path):
    chunks = _chunks(
        _doc(
            blocks=[
                {"kind": "heading", "level": 2, "text": "Facts"},
                {"kind": "paragraph", "text": "Expense ratio is 1.20 percent."},
            ]
        )
    )
    target = tmp_path / "chunks.jsonl"

    written = write_chunks(chunks, target)

    assert written == target
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(chunks)
    payload = json.loads(lines[0])
    assert payload["chunk_id"] == chunks[0].chunk_id
    assert payload["token_count"] == chunks[0].token_count
    assert payload["content_hash"] == chunks[0].content_hash


def test_read_chunks_roundtrips_written_chunks(tmp_path):
    chunks = _chunks(
        _doc(
            blocks=[
                {"kind": "heading", "level": 2, "text": "Facts"},
                {"kind": "paragraph", "text": "Expense ratio is 1.20 percent."},
                {"kind": "heading", "level": 2, "text": "Charges"},
                {"kind": "paragraph", "text": "Exit load is Nil."},
            ]
        )
    )
    target = tmp_path / "chunks.jsonl"
    write_chunks(chunks, target)

    loaded = read_chunks(target)

    assert [chunk.to_dict() for chunk in loaded] == [
        chunk.to_dict() for chunk in chunks
    ]


def test_read_chunks_rejects_hash_mismatch(tmp_path):
    chunks = _chunks(_doc())
    target = tmp_path / "chunks.jsonl"
    write_chunks(chunks, target)

    payload = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
    payload["text"] = "edited without updating the hash"
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ChunkError, match="hash mismatch"):
        read_chunks(target)


def test_read_chunks_rejects_duplicate_chunk_id(tmp_path):
    chunks = _chunks(_doc())
    target = tmp_path / "chunks.jsonl"
    write_chunks(chunks, target)

    line = target.read_text(encoding="utf-8").splitlines()[0]
    target.write_text(line + "\n" + line + "\n", encoding="utf-8")

    with pytest.raises(ChunkError, match="repeats chunk_id"):
        read_chunks(target)
