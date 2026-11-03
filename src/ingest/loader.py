"""Fetch and normalize official mutual-fund pages into raw documents.

Phase 2 of the pipeline. Reads ``data/sources.csv``, validates every URL
against the host allowlist, fetches the page with retries, extracts structured
blocks (headings, tables, lists, paragraphs), and writes one JSON document per
source plus ``data/raw/ingest_manifest.json``.

Scope rule: only the exact URLs shared in ``data/sources.csv`` are fetched.
The scraper never follows links found on a page, never downloads linked
documents (SID/KIM/fact sheet/PDFs), and drops the page's "Documents" section
from the extracted content.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

LOGGER = logging.getLogger(__name__)

# Fields the load stage requires before a raw document may be chunked.
REQUIRED_RAW_FIELDS = (
    "doc_id",
    "url",
    "title",
    "scraped_at",
    "blocks",
    "text",
    "content_hash",
)

MANIFEST_FILENAME = "ingest_manifest.json"

# Hosts that are allowed as corpus sources. The official AMFI investor
# education site is mutualfundssahihai.com (amfiindia.com links to it).
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "groww.in",
        "amfiindia.com",
        "sebi.gov.in",
        "mutualfundssahihai.com",
    }
)

MIN_SOURCES = 15
MAX_SOURCES = 25
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

REQUIRED_COLUMNS = ("id", "url", "title", "category")

HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCK_CHILD_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}

# Remove these tags before extraction. ``header`` is handled separately because
# Groww puts the scheme name and risk label inside a page-level <header>.
NOISE_TAGS = ("script", "style", "noscript", "iframe", "svg", "nav", "aside", "form", "button")

# Class-name fragments for sections that are either modal chrome or
# performance/portfolio content outside the facts-only FAQ scope.
DROP_CLASS_FRAGMENTS = (
    "rodal",  # Groww modal overlay ("Understand terms")
    "backgroundOverlay",
    "returnCalculator_container",
    "returnStats_",
    "mfGraph_",
    "returnsAndRankings_container",
    "holdings_tableContainer",
    "holdings_seeAll",
    "fundManagement_container",
)

# Small UI strings that survive DOM cleanup but carry no factual value.
NOISE_TEXTS = {
    "I Am Ready to Invest",
    "Load More",
    "More details are loading",
    "Read More",
    "Related Articles",
    "See All",
    "View details",
}

# Internal-document sections (downloadable SID/KIM/fact sheet/etc.) are not
# part of the shared source list. They are removed before chunking so no
# internal document link or document name leaks into the corpus.
INTERNAL_DOCUMENT_TITLES = {
    "document",
    "documents",
    "document download",
    "document downloads",
    "download",
    "downloads",
    "download documents",
    "downloads documents",
    "important document",
    "important documents",
    "scheme document",
    "scheme documents",
    "fund document",
    "fund documents",
    "scheme information document",
    "scheme information documents",
    "key information memorandum",
    "statement of additional information",
    "fact sheet",
    "factsheet",
    "sid",
    "kim",
    "sai",
}

_DOCUMENT_ITEM_TITLES = {
    "scheme information document",
    "scheme information documents",
    "key information memorandum",
    "statement of additional information",
    "fact sheet",
    "factsheet",
    "sid",
    "kim",
    "sai",
}

_DOWNLOAD_LABELS = {
    "download",
    "download pdf",
    "downloads",
    "link",
    "open",
    "view",
    "view pdf",
    "click here",
    "here",
}

_INTERNAL_DOCUMENT_KEYWORDS = (
    "document",
    "memorandum",
    "fact sheet",
    "factsheet",
    "statement of additional information",
)

_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


class SourceError(ValueError):
    """Raised when sources.csv is missing, malformed, or has a bad URL."""


class FetchError(RuntimeError):
    """Raised when a source cannot be fetched or yields no usable text."""


class DocumentError(RuntimeError):
    """Raised when raw documents are missing, corrupt, or fail validation."""


@dataclass(frozen=True)
class SourceSpec:
    """One row from ``data/sources.csv``."""

    id: str
    url: str
    title: str
    category: str
    aliases: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class RawDocument:
    """Normalized document written to ``data/raw/<doc_id>.json``."""

    doc_id: str
    url: str
    title: str
    category: str
    scraped_at: str
    http_status: int
    content_type: str
    blocks: list[dict]
    text: str
    content_hash: str
    aliases: tuple[str, ...] = ()
    notes: str = ""
    page_title: str = ""

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "url": self.url,
            "title": self.title,
            "category": self.category,
            "scraped_at": self.scraped_at,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "blocks": self.blocks,
            "text": self.text,
            "content_hash": self.content_hash,
            "aliases": list(self.aliases),
            "notes": self.notes,
            "page_title": self.page_title,
        }


@dataclass
class IngestResult:
    doc_id: str
    url: str
    status: str
    http_status: int | None = None
    raw_path: str | None = None
    content_hash: str | None = None
    blocks: int | None = None
    text_chars: int | None = None
    error: str | None = None
    previous_raw_kept: bool = False

    def to_dict(self) -> dict:
        payload = {
            "doc_id": self.doc_id,
            "url": self.url,
            "status": self.status,
        }
        for key in (
            "http_status",
            "raw_path",
            "content_hash",
            "blocks",
            "text_chars",
            "error",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.previous_raw_kept:
            payload["previous_raw_kept"] = True
        return payload


@dataclass
class IngestManifest:
    started_at: str
    finished_at: str
    sources_file: str
    raw_dir: str
    total: int
    succeeded: int
    failed: int
    minimum_required: int
    status: str
    source_list_hash: str
    links_followed: int = 0
    results: list[IngestResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "sources_file": self.sources_file,
            "raw_dir": self.raw_dir,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "minimum_required": self.minimum_required,
            "status": self.status,
            "source_list_hash": self.source_list_hash,
            "links_followed": self.links_followed,
            "results": [result.to_dict() for result in self.results],
        }


# ---------------------------------------------------------------------------
# Source loading and validation
# ---------------------------------------------------------------------------


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _normalize_host(host: str) -> str:
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _validate_fetched_url(final_url: str, requested_url: str) -> None:
    """Reject a fetch that ended anywhere outside the official allowlist.

    A redirect must stay on an allowlisted host. This prevents a shared page
    from silently sending the scraper to an unapproved internal/third-party
    location.
    """

    parsed = urlparse(final_url)
    host = _normalize_host(parsed.hostname or "")
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        raise FetchError(
            f"Fetch for {requested_url} ended at disallowed URL {final_url!r}; "
            "only shared allowlisted links may be scraped"
        )


def validate_source_url(url: str) -> str:
    """Return the URL if it is HTTPS and on the official allowlist."""

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SourceError(f"URL must use HTTPS: {url}")
    if parsed.username or parsed.password:
        raise SourceError(f"URL must not contain credentials: {url}")
    if parsed.port not in (None, 443):
        raise SourceError(f"URL must use the default HTTPS port: {url}")

    host = _normalize_host(parsed.hostname or "")
    if host not in ALLOWED_HOSTS:
        raise SourceError(
            f"Host {host or '<missing>'!r} is not allowed for {url}. "
            f"Allowed hosts: {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    if not parsed.path or parsed.path == "/":
        raise SourceError(f"URL must point to a page, not the site root: {url}")
    return url


def _parse_aliases(value: str | None) -> tuple[str, ...]:
    aliases: list[str] = []
    for alias in _clean(value).split("|"):
        alias = alias.strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return tuple(aliases)


def load_sources(path: str | Path) -> list[SourceSpec]:
    """Read and validate ``sources.csv``.

    Raises:
        SourceError: when the file is missing, has missing columns, duplicate
            IDs, invalid IDs, or URLs outside the allowlist.
    """

    source_path = Path(path)
    if not source_path.exists():
        raise SourceError(f"Sources file not found: {source_path}")

    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
            if missing:
                raise SourceError(
                    f"{source_path} is missing required column(s): {', '.join(missing)}"
                )

            specs: list[SourceSpec] = []
            seen_ids: set[str] = set()
            seen_urls: set[str] = set()

            for line_number, row in enumerate(reader, start=2):
                doc_id = _clean(row.get("id"))
                url = _clean(row.get("url"))
                title = _clean(row.get("title"))
                category = _clean(row.get("category")).lower()

                if not doc_id or not url or not title or not category:
                    raise SourceError(
                        f"{source_path}:{line_number} has an empty id, url, title, or category"
                    )
                if not SOURCE_ID_RE.fullmatch(doc_id):
                    raise SourceError(
                        f"{source_path}:{line_number} has invalid id {doc_id!r}; "
                        "use lowercase letters, digits, and hyphens"
                    )
                if doc_id in seen_ids:
                    raise SourceError(
                        f"{source_path}:{line_number} repeats id {doc_id!r}"
                    )
                if url in seen_urls:
                    raise SourceError(
                        f"{source_path}:{line_number} repeats url {url!r}"
                    )

                validate_source_url(url)
                seen_ids.add(doc_id)
                seen_urls.add(url)

                specs.append(
                    SourceSpec(
                        id=doc_id,
                        url=url,
                        title=title,
                        category=category,
                        aliases=_parse_aliases(row.get("aliases")),
                        notes=_clean(row.get("notes")),
                    )
                )
    except OSError as exc:
        raise SourceError(f"Could not read sources file {source_path}: {exc}") from exc

    if not specs:
        raise SourceError(f"Sources file has no data rows: {source_path}")
    return specs


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def normalize_text(value: str | None) -> str:
    """Collapse whitespace without changing numbers, units, or punctuation."""

    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def source_list_hash(specs: Iterable[SourceSpec]) -> str:
    joined = "\n".join(spec.url for spec in specs)
    return f"sha256:{hashlib.sha256(joined.encode('utf-8')).hexdigest()}"


def _class_matches(value: str | list[str] | None, fragment: str) -> bool:
    """Match a class fragment in both bs4 ``class_`` callbacks and tags.

    BeautifulSoup passes a plain string to ``class_`` callbacks in recent
    versions, while ``Tag.get("class")`` returns a list. Support both.
    """

    if not value:
        return False
    if isinstance(value, str):
        return fragment in value
    return any(fragment in entry for entry in value)


def _has_class(element: Tag, fragment: str) -> bool:
    return _class_matches(element.get("class"), fragment)


def _classes(element: Tag) -> str:
    return " ".join(element.get("class") or [])


def _text(element: Tag) -> str:
    return normalize_text(element.get_text(" ", strip=True))


def _is_noise_text(text: str) -> bool:
    if not text:
        return True
    if text in NOISE_TEXTS:
        return True
    if "More details are loading" in text:
        return True
    if text.startswith("Load More"):
        return True
    return False


def _title_key(text: str | None) -> str:
    """Normalize a heading/label for internal-document matching."""

    key = normalize_text(text).lower().rstrip(":.")
    while _TRAILING_PAREN_RE.search(key):
        key = _TRAILING_PAREN_RE.sub("", key).strip()
    return key


def _is_internal_document_heading(text: str | None) -> bool:
    """True when a heading opens a downloads/internal-documents section."""

    return _title_key(text) in INTERNAL_DOCUMENT_TITLES


def _is_internal_document_item(text: str | None) -> bool:
    """True for a document name/list item that links to an internal file."""

    key = _title_key(text)
    return key in _DOCUMENT_ITEM_TITLES or key in _DOWNLOAD_LABELS


def _is_internal_document_row(row: Sequence[str]) -> bool:
    """True when a table row is a document name paired with a download link."""

    if not row:
        return False
    label = _title_key(row[0])
    value = _title_key(" ".join(row[1:]))
    if label in INTERNAL_DOCUMENT_TITLES or label in _DOWNLOAD_LABELS:
        return True
    if any(keyword in label for keyword in _INTERNAL_DOCUMENT_KEYWORDS):
        return not value or value in _DOWNLOAD_LABELS
    return False


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


def _select_content_root(soup: BeautifulSoup) -> Tag:
    """Pick the smallest useful page container.

    Groww scheme/AMC pages expose the useful content in
    ``div.container.web-align`` and ``div.layout-main``. AMFI education pages
    use ``main``/``article``. A short container is skipped so that empty
    SPA shells do not win over the real content.
    """

    candidates = [
        soup.select_one("div.container.web-align"),
        soup.select_one("main"),
        soup.select_one("[role='main']"),
        soup.select_one("article"),
        soup.select_one("div.layout-main"),
        soup.body,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if len(_text(candidate)) > 500:
            return candidate
    return soup.body or soup


def _remove_noise(root: Tag) -> None:
    for tag_name in NOISE_TAGS:
        for element in list(root.find_all(tag_name)):
            if not getattr(element, "decomposed", False):
                element.decompose()

    # Remove the whole holdings section, not just its table, so the
    # "Holdings (64)" heading does not survive.
    for element in list(
        root.find_all(
            "div",
            class_=lambda value: _class_matches(value, "holdings_tableContainer"),
        )
    ):
        if getattr(element, "decomposed", False):
            continue
        section = element.find_parent("section")
        (section or element).decompose()

    for element in list(root.find_all(True)):
        if getattr(element, "decomposed", False):
            continue

        class_text = _classes(element)
        if any(fragment in class_text for fragment in DROP_CLASS_FRAGMENTS):
            element.decompose()
            continue

        if element.get("role") == "dialog" or element.get("aria-modal") == "true":
            element.decompose()
            continue

        if element.name == "header" and not element.find(["h1", "h2", "h3"]):
            element.decompose()
            continue

        if element.name == "footer":
            element.decompose()
            continue

        # AMFI wraps "Related Articles" / "Calculators" in this pair of
        # Tailwind classes. The real article body does not use ``w-full``.
        class_set = set(element.get("class") or [])
        if {"w-full", "overflow-hidden"} <= class_set:
            element.decompose()

def _table_rows(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            cells = row.find_all(["th", "td"])
        values = [_text(cell) for cell in cells]
        if any(values):
            rows.append(values)
    return _dedupe_rows(rows)


def _dedupe_rows(rows: Sequence[Sequence[str]]) -> list[list[str]]:
    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        values = [normalize_text(value) for value in row]
        if not any(values):
            continue
        key = tuple(values)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(values)
    return deduped


def _direct_children_with_text(element: Tag) -> list[Tag]:
    return [
        child
        for child in element.find_all(recursive=False)
        if getattr(child, "name", None) and _text(child)
    ]


def _row_from_children(element: Tag) -> list[str] | None:
    children = _direct_children_with_text(element)
    if len(children) < 2:
        return None
    label = _text(children[0])
    value = normalize_text(" ".join(_text(child) for child in children[1:]))
    if not label or not value:
        return None
    return [label, value]


def _fund_details_rows(element: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in element.find_all(
        "div",
        class_=lambda value: _class_matches(value, "fundDetails_gap"),
    ):
        row = _row_from_children(item)
        if row:
            rows.append(row)
    return _dedupe_rows(rows)


def _min_investment_rows(element: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in element.find_all(
        "div",
        class_=lambda value: _class_matches(value, "vspace-between"),
    ):
        row = _row_from_children(item)
        if row:
            rows.append(row)
    return _dedupe_rows(rows)


def _exit_load_rows(element: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    sections: list[Tag] = []
    if _has_class(element, "exitLoadStampDutyTax_section"):
        sections.append(element)
    sections.extend(
        element.find_all(
            "div",
            class_=lambda value: _class_matches(
                value, "exitLoadStampDutyTax_section"
            ),
        )
    )
    for section in sections:
        heading = section.find(list(HEADING_TAGS))
        if heading is None:
            continue
        label_text = _text(heading)
        section_text = _text(section)
        remainder = section_text
        if remainder.startswith(label_text):
            remainder = remainder[len(label_text) :].strip()

        if ":" in label_text:
            label, _, inline_value = label_text.partition(":")
            label = f"{label.strip()}:"
            value = normalize_text(" ".join(part for part in (inline_value, remainder) if part))
        else:
            label = label_text
            value = remainder

        if label and value:
            rows.append([label, value])
    return _dedupe_rows(rows)


def _benchmark_rows(element: Tag) -> list[list[str]]:
    row = _row_from_children(element)
    return [row] if row else []


def _fund_house_rows(element: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in element.find_all(
        "div",
        class_=lambda value: _class_matches(value, "fundHouse_infoItem"),
    ):
        row = _row_from_children(item)
        if row:
            rows.append(row)
    return _dedupe_rows(rows)


def _scheme_fact_rows(root: Tag) -> list[list[str]]:
    """Collect the core scheme facts into one table block.

    Keeping expense ratio, exit load, minimum SIP, benchmark, and the other
    scheme-level values in one table gives the chunker a single coherent
    "scheme facts" block, while still preserving the page's own headings.
    """

    rows: list[list[str]] = []
    selectors: list[tuple[str, Callable[[Tag], list[list[str]]]]] = [
        ("div[class*='fundDetails_fundDetailsContainer']", _fund_details_rows),
        ("div[class*='minInvestments_tableContainer']", _min_investment_rows),
        ("div[class*='exitLoadStampDutyTax_contentContainer']", _exit_load_rows),
        ("div[class*='investmentObjective_benchmarkRow']", _benchmark_rows),
    ]
    for selector, collector in selectors:
        element = root.select_one(selector)
        if element is not None:
            rows.extend(collector(element))
    return _dedupe_rows(rows)


def _container_rows(element: Tag) -> list[list[str]] | None:
    """Return key/value table rows for a known Groww container, if any."""

    if _has_class(element, "fundDetails_fundDetailsContainer"):
        return _fund_details_rows(element)
    if _has_class(element, "minInvestments_tableContainer"):
        return _min_investment_rows(element)
    if _has_class(element, "exitLoadStampDutyTax_contentContainer"):
        return _exit_load_rows(element)
    if _has_class(element, "investmentObjective_benchmarkRow"):
        return _benchmark_rows(element)
    if _has_class(element, "fundHouse_infoRow"):
        return _fund_house_rows(element)
    if _has_class(element, "fundHouse_infoItem"):
        row = _row_from_children(element)
        return [row] if row else None
    if _has_class(element, "exitLoadStampDutyTax_section"):
        rows = _exit_load_rows(element)
        return rows or None
    if _has_class(element, "fundDetails_gap"):
        row = _row_from_children(element)
        return [row] if row else None
    if _has_class(element, "vspace-between"):
        row = _row_from_children(element)
        return [row] if row else None
    return None


def _is_leaf_block(element: Tag) -> bool:
    for child in element.children:
        if getattr(child, "name", None) in BLOCK_CHILD_TAGS:
            return False
    return True


def _walk_blocks(root: Tag, category: str) -> list[dict]:
    blocks: list[dict] = []
    scheme_rows = _scheme_fact_rows(root) if category == "scheme" else []
    scheme_table_emitted = False
    # Internal-document sections appear on scheme/AMC pages. Restrict the
    # filter so education articles that merely mention "documents" survive.
    document_scope = category in {"scheme", "amc"}

    # When a scheme facts table is emitted, skip the individual containers
    # whose rows were merged into it. Their headings remain as separate blocks.
    skip_fragments = {
        "fundDetails_fundDetailsContainer",
        "minInvestments_tableContainer",
        "exitLoadStampDutyTax_contentContainer",
        "investmentObjective_benchmarkRow",
    }

    def walk(node: Tag) -> None:
        nonlocal scheme_table_emitted
        for child in node.find_all(recursive=False):
            if getattr(child, "decomposed", False):
                continue
            name = child.name
            if not name:
                continue

            text = _text(child)
            if not text:
                continue

            if name in HEADING_TAGS:
                # The shared page may link to downloadable scheme documents.
                # Those sections are not part of the source list, so drop them.
                if document_scope and _is_internal_document_heading(text):
                    continue
                blocks.append(
                    {"kind": "heading", "level": HEADING_TAGS[name], "text": text}
                )
                continue

            if name == "table":
                rows = _table_rows(child)
                if document_scope:
                    rows = [row for row in rows if not _is_internal_document_row(row)]
                if rows:
                    blocks.append({"kind": "table", "rows": rows})
                continue

            if name in {"ul", "ol"}:
                items = [
                    _text(item)
                    for item in child.find_all("li", recursive=False)
                    if _text(item)
                ]
                if document_scope:
                    items = [
                        item for item in items if not _is_internal_document_item(item)
                    ]
                if items:
                    blocks.append({"kind": "list", "items": items})
                continue

            if name == "p":
                if document_scope and _is_internal_document_item(text):
                    continue
                blocks.append({"kind": "paragraph", "text": text})
                continue

            class_text = _classes(child)
            if scheme_rows and any(fragment in class_text for fragment in skip_fragments):
                if (
                    "fundDetails_fundDetailsContainer" in class_text
                    and not scheme_table_emitted
                ):
                    blocks.append({"kind": "table", "rows": scheme_rows})
                    scheme_table_emitted = True
                continue

            rows = _container_rows(child)
            if rows:
                if document_scope:
                    rows = [row for row in rows if not _is_internal_document_row(row)]
                if rows:
                    blocks.append({"kind": "table", "rows": rows})
                continue

            if _is_leaf_block(child):
                if document_scope and _is_internal_document_item(text):
                    continue
                blocks.append({"kind": "paragraph", "text": text})
                continue

            walk(child)

    walk(root)
    return blocks


def _clean_blocks(blocks: Iterable[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for block in blocks:
        kind = block.get("kind")
        if kind in {"heading", "paragraph"}:
            text = normalize_text(block.get("text"))
            if _is_noise_text(text):
                continue
            block = {**block, "text": text}
        elif kind == "list":
            items = [
                normalize_text(item)
                for item in block.get("items", [])
                if not _is_noise_text(normalize_text(item))
            ]
            if not items:
                continue
            block = {**block, "items": items}
        elif kind == "table":
            rows = _dedupe_rows(block.get("rows", []))
            if not rows:
                continue
            block = {**block, "rows": rows}
        else:
            continue

        if cleaned and cleaned[-1] == block:
            continue
        cleaned.append(block)
    return cleaned


def blocks_to_text(blocks: Iterable[dict]) -> str:
    """Build normalized plain text with table rows on separate lines."""

    lines: list[str] = []
    for block in blocks:
        kind = block.get("kind")
        if kind in {"heading", "paragraph"}:
            lines.append(block["text"])
        elif kind == "list":
            lines.extend(block["items"])
        elif kind == "table":
            for row in block["rows"]:
                lines.append(" | ".join(row))
    return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class ExtractedPage:
    blocks: list[dict]
    text: str
    page_title: str


def extract_page(html: str, category: str = "") -> ExtractedPage:
    """Extract structured blocks and normalized text from an HTML page."""

    soup = BeautifulSoup(html, "lxml")
    page_title = normalize_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

    # Drop non-content tags before choosing a container so embedded JSON in a
    # script tag cannot make an otherwise empty SPA shell look substantial.
    for tag_name in ("script", "style", "noscript", "template"):
        for element in list(soup.find_all(tag_name)):
            element.decompose()

    root = _select_content_root(soup)
    _remove_noise(root)
    blocks = _clean_blocks(_walk_blocks(root, category))
    text = blocks_to_text(blocks)
    return ExtractedPage(blocks=blocks, text=text, page_title=page_title)


# ---------------------------------------------------------------------------
# Fetching and persistence
# ---------------------------------------------------------------------------


def _content_type(category: str) -> str:
    return {
        "scheme": "scheme_page",
        "amc": "amc_page",
        "education": "education_page",
        "regulator": "regulator_page",
    }.get(category, "page")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def fetch_document(
    spec: SourceSpec,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
) -> RawDocument:
    """Fetch one source and return its normalized raw document."""

    if retries < 1:
        raise ValueError("retries must be at least 1")

    http = session or requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    response: requests.Response | None = None
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = http.get(spec.url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(backoff * (2**attempt))
                continue
            raise FetchError(f"Could not fetch {spec.url}: {exc}") from exc

        if response.status_code == 200:
            break

        if response.status_code in {429, 500, 502, 503, 504} and attempt < retries - 1:
            time.sleep(backoff * (2**attempt))
            continue

        raise FetchError(f"HTTP {response.status_code} for {spec.url}")

    if response is None or response.status_code != 200:
        raise FetchError(f"Could not fetch {spec.url}: {last_error or 'no response'}")

    content_type = response.headers.get("Content-Type", "")
    if content_type and "html" not in content_type.lower():
        raise FetchError(
            f"Unexpected Content-Type {content_type!r} for {spec.url}; expected HTML"
        )

    # Only the shared URL (or a same-allowlist redirect of it) is in scope.
    # Linked documents and internal links on the page are never fetched.
    _validate_fetched_url(getattr(response, "url", None) or spec.url, spec.url)

    page = extract_page(response.text, spec.category)
    if not page.text.strip():
        raise FetchError(f"No extractable text for {spec.url}")

    return RawDocument(
        doc_id=spec.id,
        url=spec.url,
        title=spec.title,
        category=spec.category,
        scraped_at=utc_now_iso(),
        http_status=response.status_code,
        content_type=_content_type(spec.category),
        blocks=page.blocks,
        text=page.text,
        content_hash=content_hash(page.text),
        aliases=spec.aliases,
        notes=spec.notes,
        page_title=page.page_title,
    )


def load_all(
    specs: Sequence[SourceSpec],
    raw_dir: str | Path,
    *,
    sources_file: str | Path = "data/sources.csv",
    fetcher: Callable[[SourceSpec], RawDocument] = fetch_document,
    minimum_required: int = MIN_SOURCES,
) -> IngestManifest:
    """Fetch every source, write raw documents, and write the manifest.

    A failed source is recorded in the manifest and never overwrites an
    existing good raw document. The run is marked successful only when at
    least ``minimum_required`` sources succeeded.
    """

    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    results: list[IngestResult] = []

    for spec in specs:
        target = raw_path / f"{spec.id}.json"
        try:
            document = fetcher(spec)
            if document.doc_id != spec.id:
                raise ValueError(
                    f"Fetcher returned doc_id {document.doc_id!r} for source {spec.id!r}"
                )
            if document.url != spec.url:
                raise ValueError(
                    f"Fetcher returned url {document.url!r} for source {spec.url!r}"
                )
            if not document.text.strip():
                raise ValueError("Fetcher returned a document with no text")

            _write_json_atomic(target, document.to_dict())
            results.append(
                IngestResult(
                    doc_id=spec.id,
                    url=spec.url,
                    status="ok",
                    http_status=document.http_status,
                    raw_path=str(target),
                    content_hash=document.content_hash,
                    blocks=len(document.blocks),
                    text_chars=len(document.text),
                )
            )
        except Exception as exc:  # noqa: BLE001 - failures are recorded, not raised
            results.append(
                IngestResult(
                    doc_id=spec.id,
                    url=spec.url,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    previous_raw_kept=target.exists(),
                )
            )

    finished_at = utc_now_iso()
    succeeded = sum(1 for result in results if result.status == "ok")
    failed = len(results) - succeeded
    status = "success" if succeeded >= minimum_required else "failed"

    manifest = IngestManifest(
        started_at=started_at,
        finished_at=finished_at,
        sources_file=str(sources_file),
        raw_dir=str(raw_path),
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        minimum_required=minimum_required,
        status=status,
        source_list_hash=source_list_hash(specs),
        results=results,
    )
    _write_json_atomic(raw_path / "ingest_manifest.json", manifest.to_dict())
    return manifest


# ---------------------------------------------------------------------------
# Phase 3: load and validate raw documents
# ---------------------------------------------------------------------------


def _read_json_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentError(f"Could not read raw document {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DocumentError(f"Raw document {path} must contain a JSON object")
    return payload


def _read_ingest_manifest(raw_path: Path, minimum_required: int) -> dict:
    manifest_path = raw_path / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise DocumentError(
            f"Missing {manifest_path}; run `python -m src.ingest.pipeline --stage load` first"
        )

    manifest = _read_json_object(manifest_path)
    succeeded = manifest.get("succeeded")
    if not isinstance(succeeded, int) or isinstance(succeeded, bool):
        raise DocumentError(
            f"{manifest_path} has no valid integer 'succeeded' count"
        )
    if succeeded < minimum_required:
        raise DocumentError(
            f"{manifest_path} reports {succeeded} succeeded source(s); "
            f"at least {minimum_required} are required. Run scraping again."
        )
    return manifest


def _validate_required_raw_fields(payload: dict, path: Path) -> None:
    missing = [name for name in REQUIRED_RAW_FIELDS if name not in payload]
    if missing:
        raise DocumentError(
            f"Raw document {path} is missing required field(s): {', '.join(missing)}"
        )

    for name in ("doc_id", "url", "title", "scraped_at", "text", "content_hash"):
        if not isinstance(payload[name], str):
            raise DocumentError(
                f"Raw document {path} field {name!r} must be a string"
            )

    # ``text`` and ``blocks`` may be empty; those documents are rejected later
    # (skipped) rather than aborting the whole load stage.
    for name in ("doc_id", "url", "title", "scraped_at", "content_hash"):
        if not payload[name].strip():
            raise DocumentError(
                f"Raw document {path} field {name!r} must not be empty"
            )

    if not isinstance(payload["blocks"], list):
        raise DocumentError(f"Raw document {path} field 'blocks' must be a list")
    if any(not isinstance(block, dict) for block in payload["blocks"]):
        raise DocumentError(
            f"Raw document {path} has a block that is not a JSON object"
        )


def _raw_document_from_payload(
    payload: dict,
    path: Path,
    spec: SourceSpec,
) -> RawDocument:
    _validate_required_raw_fields(payload, path)

    category = payload.get("category") or spec.category
    if not isinstance(category, str) or not category.strip():
        raise DocumentError(f"Raw document {path} has an invalid 'category'")
    category = category.strip().lower()

    http_status = payload.get("http_status", 200)
    if not isinstance(http_status, int) or isinstance(http_status, bool):
        raise DocumentError(f"Raw document {path} has an invalid 'http_status'")

    content_type = payload.get("content_type") or _content_type(category)
    if not isinstance(content_type, str) or not content_type.strip():
        raise DocumentError(f"Raw document {path} has an invalid 'content_type'")

    aliases = payload.get("aliases", list(spec.aliases))
    if not isinstance(aliases, (list, tuple)):
        raise DocumentError(f"Raw document {path} has an invalid 'aliases' value")

    notes = payload.get("notes", spec.notes)
    if not isinstance(notes, str):
        raise DocumentError(f"Raw document {path} has an invalid 'notes' value")

    page_title = payload.get("page_title", "")
    if not isinstance(page_title, str):
        raise DocumentError(f"Raw document {path} has an invalid 'page_title' value")

    return RawDocument(
        doc_id=payload["doc_id"],
        url=payload["url"],
        title=payload["title"],
        category=category,
        scraped_at=payload["scraped_at"],
        http_status=http_status,
        content_type=content_type,
        blocks=payload["blocks"],
        text=payload["text"],
        content_hash=payload["content_hash"],
        aliases=tuple(str(alias) for alias in aliases),
        notes=notes,
        page_title=page_title,
    )


def load_raw_documents(
    raw_dir: str | Path,
    sources: Sequence[SourceSpec],
    *,
    minimum_required: int = MIN_SOURCES,
) -> list[RawDocument]:
    """Load, validate, and sort the raw documents written by the scraper.

    This is the bridge between scraping and chunking. It never reads HTML and
    never re-fetches a URL; it only trusts ``data/raw/*.json`` after checking
    every document against ``sources.csv`` and the stored content hash.

    Stop conditions (raise ``DocumentError``):
        * missing manifest or ``succeeded < minimum_required``
        * unreadable/corrupt JSON, missing required fields, or bad types
        * content hash mismatch
        * duplicate ``doc_id``

    Rejections (logged and skipped):
        * URL is not present in ``sources.csv``
        * URL host is outside the allowlist
        * empty ``text`` or empty ``blocks``
    """

    raw_path = Path(raw_dir)
    if not raw_path.exists():
        raise DocumentError(f"Raw directory not found: {raw_path}")

    manifest = _read_ingest_manifest(raw_path, minimum_required)
    source_by_url = {spec.url: spec for spec in sources}

    documents: list[RawDocument] = []
    seen_ids: set[str] = set()
    rejected = 0

    for path in sorted(raw_path.glob("*.json")):
        if path.name == MANIFEST_FILENAME:
            continue

        payload = _read_json_object(path)
        _validate_required_raw_fields(payload, path)

        url = payload["url"]
        try:
            validate_source_url(url)
        except SourceError as exc:
            LOGGER.warning("Rejecting raw document %s: %s", path.name, exc)
            rejected += 1
            continue

        spec = source_by_url.get(url)
        if spec is None:
            LOGGER.warning(
                "Rejecting raw document %s: URL %s is not in sources.csv",
                path.name,
                url,
            )
            rejected += 1
            continue

        if not payload["text"].strip() or not payload["blocks"]:
            LOGGER.warning(
                "Rejecting raw document %s: empty text or blocks", path.name
            )
            rejected += 1
            continue

        actual_hash = content_hash(payload["text"])
        if actual_hash != payload["content_hash"]:
            raise DocumentError(
                f"Content hash mismatch for {path}: stored "
                f"{payload['content_hash']!r}, recomputed {actual_hash!r}"
            )

        document = _raw_document_from_payload(payload, path, spec)
        if document.doc_id in seen_ids:
            raise DocumentError(
                f"Duplicate doc_id {document.doc_id!r} found in {path}"
            )
        seen_ids.add(document.doc_id)
        documents.append(document)

    if not documents:
        raise DocumentError(f"No valid raw documents found in {raw_path}")

    documents.sort(key=lambda document: document.doc_id)

    total_chars = sum(len(document.text) for document in documents)
    LOGGER.info(
        "Loaded %d raw document(s) (%d characters) from %s",
        len(documents),
        total_chars,
        raw_path,
    )

    succeeded = manifest.get("succeeded", 0)
    if rejected:
        LOGGER.warning(
            "Rejected %d raw document file(s) while loading %s",
            rejected,
            raw_path,
        )
    if len(documents) < succeeded:
        LOGGER.warning(
            "Loaded %d document(s) but the manifest reports %s succeeded; "
            "some raw documents were rejected",
            len(documents),
            succeeded,
        )

    return documents
