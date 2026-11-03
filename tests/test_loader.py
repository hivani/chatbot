import json
from pathlib import Path

import pytest
import requests

from src.ingest.loader import (
    MANIFEST_FILENAME,
    DocumentError,
    FetchError,
    RawDocument,
    SourceError,
    SourceSpec,
    content_hash,
    extract_page,
    fetch_document,
    load_all,
    load_raw_documents,
    load_sources,
    utc_now_iso,
    validate_source_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHEME_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"


def _fixture_html() -> str:
    return (FIXTURES / "scheme_page.html").read_text(encoding="utf-8")


def _write_sources(path: Path, rows: list[str]) -> Path:
    path.write_text(
        "id,url,title,category,aliases,notes\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    return path


def _spec(doc_id: str = "test-scheme", url: str = SCHEME_URL) -> SourceSpec:
    return SourceSpec(
        id=doc_id,
        url=url,
        title="HDFC Test ELSS Fund Direct Plan Growth",
        category="scheme",
        aliases=("HDFC Test",),
        notes="fixture",
    )


def _raw_document(spec: SourceSpec) -> RawDocument:
    text = "HDFC Test ELSS Fund Direct Plan Growth\nExpense ratio | 1.20%"
    return RawDocument(
        doc_id=spec.id,
        url=spec.url,
        title=spec.title,
        category=spec.category,
        scraped_at=utc_now_iso(),
        http_status=200,
        content_type="scheme_page",
        blocks=[{"kind": "paragraph", "text": "HDFC Test ELSS Fund Direct Plan Growth"}],
        text=text,
        content_hash=content_hash(text),
    )


# ---------------------------------------------------------------------------
# sources.csv
# ---------------------------------------------------------------------------


def test_load_sources_parses_rows(tmp_path):
    path = _write_sources(
        tmp_path / "sources.csv",
        [
            "test-scheme,https://groww.in/mutual-funds/test-scheme,Test Scheme,scheme,Test|Scheme,note",
            "test-edu,https://www.mutualfundssahihai.com/en/test,Test Education,education,,note",
        ],
    )

    specs = load_sources(path)

    assert [spec.id for spec in specs] == ["test-scheme", "test-edu"]
    assert specs[0].aliases == ("Test", "Scheme")
    assert specs[1].aliases == ()
    assert specs[0].category == "scheme"


def test_load_sources_rejects_non_allowlisted_host(tmp_path):
    path = _write_sources(
        tmp_path / "sources.csv",
        ["bad,https://example.com/page,Bad,education,,"],
    )

    with pytest.raises(SourceError, match="not allowed"):
        load_sources(path)


def test_load_sources_rejects_http(tmp_path):
    path = _write_sources(
        tmp_path / "sources.csv",
        ["bad,http://groww.in/mutual-funds/test,Bad,scheme,,"],
    )

    with pytest.raises(SourceError, match="HTTPS"):
        load_sources(path)


def test_load_sources_rejects_duplicate_ids(tmp_path):
    path = _write_sources(
        tmp_path / "sources.csv",
        [
            "same,https://groww.in/mutual-funds/one,One,scheme,,",
            "same,https://groww.in/mutual-funds/two,Two,scheme,,",
        ],
    )

    with pytest.raises(SourceError, match="repeats id"):
        load_sources(path)


def test_load_sources_rejects_duplicate_urls(tmp_path):
    path = _write_sources(
        tmp_path / "sources.csv",
        [
            "one,https://groww.in/mutual-funds/one,One,scheme,,",
            "two,https://groww.in/mutual-funds/one,Two,scheme,,",
        ],
    )

    with pytest.raises(SourceError, match="repeats url"):
        load_sources(path)


def test_load_sources_rejects_missing_columns(tmp_path):
    path = tmp_path / "sources.csv"
    path.write_text("id,url\none,https://groww.in/mutual-funds/one\n", encoding="utf-8")

    with pytest.raises(SourceError, match="missing required column"):
        load_sources(path)


def test_validate_source_url_accepts_allowed_hosts():
    for url in (
        "https://groww.in/mutual-funds/test",
        "https://www.groww.in/mutual-funds/test",
        "https://www.amfiindia.com/investor-corner",
        "https://www.sebi.gov.in/page",
        "https://www.mutualfundssahihai.com/en/what-is-sip",
    ):
        assert validate_source_url(url) == url


def test_validate_source_url_rejects_site_root():
    with pytest.raises(SourceError, match="site root"):
        validate_source_url("https://groww.in/")


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


def test_extract_page_removes_nav_footer_modal_and_performance_noise():
    page = extract_page(_fixture_html(), category="scheme")

    assert page.page_title.startswith("HDFC Test ELSS Fund Direct Plan Growth")
    assert "should not appear" not in page.text
    assert "Footer links" not in page.text
    assert "Login" not in page.text
    assert "A fee payable to a mutual fund house" not in page.text
    assert "Return calculator" not in page.text
    assert "Historic returns" not in page.text
    assert "Fund returns" not in page.text
    assert "Manager details" not in page.text
    assert "Holdings" not in page.text


def test_extract_page_keeps_headings_tables_lists_and_paragraphs():
    page = extract_page(_fixture_html(), category="scheme")

    headings = [block["text"] for block in page.blocks if block["kind"] == "heading"]
    assert "HDFC Test ELSS Fund Direct Plan Growth" in headings
    assert "Exit load, stamp duty and tax" in headings

    assert any(
        block["kind"] == "table"
        and any(row[0] == "Expense ratio" for row in block["rows"])
        for block in page.blocks
    )
    assert any(
        block["kind"] == "paragraph"
        and "Mutual fund investments are subject to market risks." in block["text"]
        for block in page.blocks
    )


def test_extract_page_excludes_internal_documents_and_links():
    page = extract_page(_fixture_html(), category="scheme")

    headings = [block["text"] for block in page.blocks if block["kind"] == "heading"]
    assert "Documents" not in headings
    assert "Document" not in page.text
    assert "Scheme Information Document" not in page.text
    assert "Fact sheet" not in page.text
    assert "Key Information Memorandum" not in page.text
    assert "Download" not in page.text

    # Document tables/lists are removed wholesale, but unrelated prose that
    # happens to sit in the same container is preserved.
    assert not any(
        block["kind"] == "table" and ["Document", "Link"] in block["rows"]
        for block in page.blocks
    )
    assert "Mutual fund investments are subject to market risks." in page.text


def test_extract_page_removes_only_document_rows_from_mixed_table():
    html = """
    <html><head><title>Facts</title></head><body>
      <main><article>
        <h2>Documents</h2>
        <table>
          <tr><th>Expense ratio</th><th>0.50%</th></tr>
          <tr><td>Scheme Information Document</td><td>Download</td></tr>
          <tr><td>Fact sheet</td><td>Download PDF</td></tr>
        </table>
        <ul>
          <li>Key Information Memorandum</li>
          <li>Scheme Information Document (SID)</li>
          <li>Exit load is Nil.</li>
        </ul>
      </article></main>
    </body></html>
    """

    page = extract_page(html, category="scheme")

    tables = [block for block in page.blocks if block["kind"] == "table"]
    assert tables
    rows = [row for table in tables for row in table["rows"]]
    assert ["Expense ratio", "0.50%"] in rows
    assert not any("Document" in row[0] for row in rows)
    assert not any("Fact sheet" in row[0] for row in rows)

    items = [item for block in page.blocks if block["kind"] == "list" for item in block["items"]]
    assert "Key Information Memorandum" not in items
    assert "Scheme Information Document (SID)" not in items
    assert "Exit load is Nil." in items


def test_extract_page_does_not_store_link_targets():
    html = """
    <html><head><title>Facts</title></head><body>
      <main><article>
        <h1>HDFC Test Fund</h1>
        <p>See <a href="https://groww.in/internal/scheme-information-document.pdf">
        the scheme page</a> for details.</p>
      </article></main>
    </body></html>
    """

    page = extract_page(html, category="scheme")

    assert "the scheme page" in page.text
    assert "scheme-information-document.pdf" not in page.text
    assert "groww.in/internal" not in page.text


def test_education_statement_heading_is_not_treated_as_documents_section():
    html = """
    <html><head><title>Statement</title></head><body>
      <main><article>
        <h1>How to Get Capital Gain Statement for Mutual Funds?</h1>
        <p>You can download the statement from the registrar.</p>
      </article></main>
    </body></html>
    """

    page = extract_page(html, category="education")

    assert "How to Get Capital Gain Statement" in page.text
    assert "download the statement" in page.text


def test_scheme_facts_table_contains_expense_ratio_and_exit_load():
    page = extract_page(_fixture_html(), category="scheme")

    fact_tables = [
        block
        for block in page.blocks
        if block["kind"] == "table"
        and any(row[0] == "Expense ratio" for row in block["rows"])
    ]
    assert fact_tables, "expected a scheme facts table"

    rows = fact_tables[0]["rows"]
    assert ["Expense ratio", "1.20%"] in rows
    assert ["Exit load", "Nil"] in rows
    assert ["Min. for SIP", "₹500"] in rows
    assert ["Fund benchmark", "NIFTY 500 Total Return Index"] in rows
    assert ["NAV: 30 Oct '26", "₹1,434.92"] in rows


def test_extract_page_emits_fund_house_table():
    page = extract_page(_fixture_html(), category="scheme")

    assert any(
        block["kind"] == "table"
        and ["Total AUM", "₹9,34,075.66 Cr"] in block["rows"]
        for block in page.blocks
    )


def test_extract_page_handles_education_page_without_scheme_container():
    html = """
    <html><head><title>What is SIP?</title></head><body>
      <main>
        <article>
          <h1>What is SIP?</h1>
          <div class="text-grey-dark">
            <p>A SIP is a systematic investment plan.</p>
            <ul><li>Invest regularly</li><li>Rupee-cost averaging</li></ul>
            <table><tr><th>Feature</th><th>Detail</th></tr>
            <tr><td>Frequency</td><td>Monthly</td></tr></table>
          </div>
        </article>
      </main>
    </body></html>
    """

    page = extract_page(html, category="education")

    assert page.text.startswith("What is SIP?")
    assert "A SIP is a systematic investment plan." in page.text
    assert any(block["kind"] == "list" for block in page.blocks)
    assert any(block["kind"] == "table" for block in page.blocks)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        text: str | None = None,
        url: str | None = None,
    ):
        self.status_code = status_code
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.text = _fixture_html() if text is None else text
        self.url = url


class _FlakySession:
    def __init__(self, failures: int = 2, status_code: int = 200):
        self.failures = failures
        self.status_code = status_code
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("temporary network error")
        return _FakeResponse(self.status_code)


class _RecordingSession:
    def __init__(self, response: _FakeResponse | None = None):
        self.urls: list[str] = []
        self._response = response

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return self._response or _FakeResponse(url=url)


def test_fetch_document_retries_then_builds_raw_document():
    session = _FlakySession(failures=2)

    document = fetch_document(_spec(), session=session, backoff=0)

    assert session.calls == 3
    assert document.doc_id == "test-scheme"
    assert document.http_status == 200
    assert document.content_type == "scheme_page"
    assert document.text
    assert document.content_hash.startswith("sha256:")
    assert document.blocks
    assert document.page_title.startswith("HDFC Test ELSS")


def test_fetch_document_raises_on_non_retryable_http_error():
    session = _FlakySession(failures=0, status_code=404)

    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_document(_spec(), session=session, backoff=0)


def test_fetch_document_raises_after_retry_budget():
    session = _FlakySession(failures=3)

    with pytest.raises(FetchError, match="Could not fetch"):
        fetch_document(_spec(), session=session, retries=3, backoff=0)


def test_fetch_document_fetches_only_the_shared_url():
    spec = _spec()
    session = _RecordingSession()

    fetch_document(spec, session=session, backoff=0)

    # No crawl: exactly one request, to the URL listed in sources.csv. Links
    # present in the page HTML are never followed.
    assert session.urls == [spec.url]


def test_fetch_document_rejects_redirect_off_the_allowlist():
    spec = _spec()
    session = _RecordingSession(
        _FakeResponse(url="https://example.com/internal/scheme-information.pdf")
    )

    with pytest.raises(FetchError, match="disallowed URL"):
        fetch_document(spec, session=session, backoff=0)


def test_fetch_document_allows_same_allowlist_redirect():
    spec = _spec()
    redirected = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
    session = _RecordingSession(_FakeResponse(url=redirected))

    document = fetch_document(spec, session=session, backoff=0)

    assert document.url == spec.url


# ---------------------------------------------------------------------------
# Manifest and failure handling
# ---------------------------------------------------------------------------


def test_load_all_writes_raw_files_and_manifest(tmp_path):
    spec = _spec()

    manifest = load_all(
        [spec],
        tmp_path,
        fetcher=_raw_document,
        minimum_required=1,
    )

    assert manifest.status == "success"
    assert (manifest.total, manifest.succeeded, manifest.failed) == (1, 1, 0)

    raw_file = tmp_path / "test-scheme.json"
    assert raw_file.exists()
    payload = json.loads(raw_file.read_text(encoding="utf-8"))
    assert payload["doc_id"] == "test-scheme"
    assert payload["content_hash"].startswith("sha256:")

    manifest_payload = json.loads(
        (tmp_path / "ingest_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["succeeded"] == 1
    assert manifest_payload["failed"] == 0
    assert manifest_payload["links_followed"] == 0
    assert manifest_payload["results"][0]["status"] == "ok"


def test_failed_fetch_keeps_last_good_raw_document(tmp_path):
    spec = _spec()
    good_file = tmp_path / "test-scheme.json"
    good_payload = '{"doc_id": "test-scheme", "text": "old good document"}'
    good_file.write_text(good_payload, encoding="utf-8")

    def failing_fetcher(source: SourceSpec) -> RawDocument:
        raise FetchError("network down")

    manifest = load_all(
        [spec],
        tmp_path,
        fetcher=failing_fetcher,
        minimum_required=1,
    )

    assert manifest.status == "failed"
    assert manifest.failed == 1
    assert good_file.read_text(encoding="utf-8") == good_payload

    result = manifest.results[0]
    assert result.status == "failed"
    assert result.previous_raw_kept is True
    assert "network down" in result.error


def test_load_all_marks_run_failed_below_minimum(tmp_path):
    spec = _spec()

    manifest = load_all(
        [spec],
        tmp_path,
        fetcher=_raw_document,
        minimum_required=15,
    )

    assert manifest.status == "failed"
    assert manifest.succeeded == 1
    assert manifest.minimum_required == 15


def test_load_all_records_empty_document_as_failure(tmp_path):
    spec = _spec()

    def empty_fetcher(source: SourceSpec) -> RawDocument:
        document = _raw_document(source)
        return RawDocument(
            doc_id=document.doc_id,
            url=document.url,
            title=document.title,
            category=document.category,
            scraped_at=document.scraped_at,
            http_status=document.http_status,
            content_type=document.content_type,
            blocks=[],
            text="",
            content_hash=content_hash(""),
        )

    manifest = load_all(
        [spec],
        tmp_path,
        fetcher=empty_fetcher,
        minimum_required=1,
    )

    assert manifest.failed == 1
    assert not (tmp_path / "test-scheme.json").exists()
    assert "no text" in manifest.results[0].error


def test_content_hash_is_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
    assert content_hash("abc").startswith("sha256:")


# ---------------------------------------------------------------------------
# Phase 3: load and validate raw documents
# ---------------------------------------------------------------------------

A_URL = "https://groww.in/mutual-funds/a-fund"
B_URL = "https://groww.in/mutual-funds/b-fund"


def _write_manifest(raw_dir: Path, *, succeeded: int, failed: int = 0) -> Path:
    path = raw_dir / MANIFEST_FILENAME
    path.write_text(
        json.dumps(
            {
                "total": succeeded + failed,
                "succeeded": succeeded,
                "failed": failed,
                "status": "success" if failed == 0 else "failed",
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_raw(
    raw_dir: Path,
    spec: SourceSpec,
    *,
    filename: str | None = None,
    **overrides,
) -> Path:
    payload = _raw_document(spec).to_dict()
    payload.update(overrides)
    path = raw_dir / (filename or f"{spec.id}.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_raw_documents_loads_and_sorts_valid_documents(tmp_path):
    specs = [_spec("b-doc", B_URL), _spec("a-doc", A_URL)]
    _write_manifest(tmp_path, succeeded=2)
    _write_raw(tmp_path, specs[0])
    _write_raw(tmp_path, specs[1])

    documents = load_raw_documents(tmp_path, specs, minimum_required=1)

    assert [document.doc_id for document in documents] == ["a-doc", "b-doc"]
    assert [document.url for document in documents] == [A_URL, B_URL]
    assert all(document.blocks and document.text for document in documents)


def test_load_raw_documents_requires_manifest(tmp_path):
    specs = [_spec()]

    with pytest.raises(DocumentError, match="Missing"):
        load_raw_documents(tmp_path, specs, minimum_required=1)


def test_load_raw_documents_enforces_manifest_minimum(tmp_path):
    specs = [_spec()]
    _write_manifest(tmp_path, succeeded=1)
    _write_raw(tmp_path, specs[0])

    with pytest.raises(DocumentError, match="at least 15"):
        load_raw_documents(tmp_path, specs, minimum_required=15)


def test_load_raw_documents_stops_on_corrupt_json(tmp_path):
    specs = [_spec()]
    _write_manifest(tmp_path, succeeded=1)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(DocumentError, match="Could not read"):
        load_raw_documents(tmp_path, specs, minimum_required=1)


def test_load_raw_documents_stops_on_missing_required_field(tmp_path):
    specs = [_spec()]
    _write_manifest(tmp_path, succeeded=1)
    payload = _raw_document(specs[0]).to_dict()
    payload.pop("text")
    (tmp_path / "missing.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DocumentError, match="missing required field"):
        load_raw_documents(tmp_path, specs, minimum_required=1)


def test_load_raw_documents_stops_on_hash_mismatch(tmp_path):
    specs = [_spec()]
    _write_manifest(tmp_path, succeeded=1)
    _write_raw(tmp_path, specs[0], text="edited after scraping")

    with pytest.raises(DocumentError, match="hash mismatch"):
        load_raw_documents(tmp_path, specs, minimum_required=1)


def test_load_raw_documents_stops_on_duplicate_doc_id(tmp_path):
    specs = [_spec("a-doc", A_URL), _spec("b-doc", B_URL)]
    _write_manifest(tmp_path, succeeded=2)
    _write_raw(tmp_path, specs[0])
    _write_raw(tmp_path, specs[1], doc_id="a-doc")

    with pytest.raises(DocumentError, match="Duplicate doc_id"):
        load_raw_documents(tmp_path, specs, minimum_required=1)


def test_load_raw_documents_rejects_url_not_in_sources(tmp_path):
    specs = [_spec("a-doc", A_URL)]
    _write_manifest(tmp_path, succeeded=2)
    _write_raw(tmp_path, specs[0])
    _write_raw(tmp_path, specs[0], filename="outside.json", doc_id="outside", url=B_URL)

    documents = load_raw_documents(tmp_path, specs, minimum_required=1)

    assert [document.doc_id for document in documents] == ["a-doc"]


def test_load_raw_documents_rejects_non_allowlisted_host(tmp_path):
    specs = [_spec("a-doc", A_URL)]
    _write_manifest(tmp_path, succeeded=2)
    _write_raw(tmp_path, specs[0])
    _write_raw(
        tmp_path,
        specs[0],
        filename="bad.json",
        doc_id="bad",
        url="https://example.com/page",
    )

    documents = load_raw_documents(tmp_path, specs, minimum_required=1)

    assert [document.doc_id for document in documents] == ["a-doc"]


def test_load_raw_documents_rejects_empty_text_or_blocks(tmp_path):
    specs = [_spec("a-doc", A_URL)]
    _write_manifest(tmp_path, succeeded=3)
    _write_raw(tmp_path, specs[0])
    _write_raw(
        tmp_path,
        specs[0],
        filename="empty-text.json",
        doc_id="empty-text",
        text="",
        content_hash=content_hash(""),
    )
    _write_raw(tmp_path, specs[0], filename="empty-blocks.json", doc_id="empty-blocks", blocks=[])

    documents = load_raw_documents(tmp_path, specs, minimum_required=1)

    assert [document.doc_id for document in documents] == ["a-doc"]


def test_load_raw_documents_rejects_when_all_files_are_invalid(tmp_path):
    specs = [_spec("a-doc", A_URL)]
    _write_manifest(tmp_path, succeeded=1)
    _write_raw(tmp_path, specs[0], text="", content_hash=content_hash(""))

    with pytest.raises(DocumentError, match="No valid raw documents"):
        load_raw_documents(tmp_path, specs, minimum_required=1)

