"""Post-generation validation.

The model never writes a URL; it returns a 1-based ``citation_index`` that is
resolved against the retrieved chunks here. Validation enforces the answer
contract from ``implementation.md`` §7.5 and ``architecture.md`` §7.4.
Unvalidated text is never returned to the user.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.guardrails.pii import contains_pii
from src.rag.prompts import DISCLAIMER


class CompletionParseError(ValueError):
    """Raised when a completion is not a JSON object."""


class InsufficientCompletion(RuntimeError):
    """Raised when the model says the context does not contain the fact."""


class ValidationError(ValueError):
    """Raised when a completion violates the answer contract."""

    def __init__(self, errors: Sequence[str], checks: Mapping[str, bool] | None = None):
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)
        self.checks = dict(checks or {})


@dataclass(frozen=True)
class ValidatedAnswer:
    """A completion that passed every post-generation check."""

    answer: str
    citation_index: int
    citation_url: str
    citation_title: str
    last_updated: str
    used_chunk_ids: tuple[str, ...]
    sentence_count: int
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citation_index": self.citation_index,
            "citation_url": self.citation_url,
            "citation_title": self.citation_title,
            "last_updated": self.last_updated,
            "used_chunk_ids": list(self.used_chunk_ids),
            "sentence_count": self.sentence_count,
            "checks": dict(self.checks),
        }


_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_NUMBER = re.compile(
    r"(?<![\w.])(?:₹|rs\.?|inr|\$)?\s?"
    r"(\d[\d,]*(?:\.\d+)?)"
    r"\s?(%|percent\b)?",
    re.IGNORECASE,
)
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_ADVICE_LANGUAGE: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\byou\s+(?:should|must|need\s+to|have\s+to)\s+"
        r"(?:buy|sell|hold|invest|switch|redeem)\b"
    ),
    re.compile(r"(?i)\b(?:i|we)\s+(?:would\s+)?(?:recommend|suggest|advise)\b"),
    re.compile(
        r"(?i)\b(?:consider|go\s+ahead\s+and)\s+"
        r"(?:buying|selling|holding|investing)\b"
    ),
    re.compile(
        r"(?i)\b(?:buy|sell|hold)\s+(?:this|the|these|your)\s+"
        r"(?:fund|scheme|units?|investment)\b"
    ),
    re.compile(r"(?i)\bguaranteed?\b"),
    re.compile(r"(?i)\bassured\s+returns?\b"),
    re.compile(r"(?i)\bbest\s+(?:fund|scheme|investment)\b"),
    re.compile(r"(?i)\bsafe\s+bet\b"),
    re.compile(r"(?i)\bworth\s+it\b"),
    re.compile(r"(?i)\bwould\s+be\s+a\s+good\s+investment\b"),
)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating markdown fences or nearby prose."""

    raw = (text or "").strip()
    if not raw:
        raise CompletionParseError("Completion is empty")

    if raw.startswith("```"):
        raw = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        raise CompletionParseError("Completion does not contain a JSON object")

    candidate = raw[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise CompletionParseError(f"Completion is not valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise CompletionParseError("Completion JSON must be an object")
    return payload


def count_sentences(text: str) -> int:
    """Count sentence-ending punctuation followed by whitespace or end."""

    stripped = (text or "").strip()
    if not stripped:
        return 0
    endings = len(_SENTENCE_END.findall(stripped))
    return endings or 1


def _normalize_number(value: str, percentage: str | None) -> str:
    number = value.replace(",", "")
    try:
        numeric = float(number)
    except ValueError:
        return number.casefold()
    rendered = f"{numeric:g}"
    if percentage:
        return f"{rendered}%"
    return rendered


def extract_numbers(text: str) -> set[str]:
    """Return normalized numeric tokens used for grounding checks."""

    numbers: set[str] = set()
    for match in _NUMBER.finditer(text or ""):
        numbers.add(_normalize_number(match.group(1), match.group(2)))
    return numbers


def contains_advice_language(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _ADVICE_LANGUAGE)


def _is_iso_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return True


def validate_completion(
    payload: Mapping[str, Any],
    chunks: Sequence[Any],
    *,
    max_sentences: int = 3,
    disclaimer: str = DISCLAIMER,
) -> ValidatedAnswer:
    """Validate a parsed completion and resolve its citation."""

    checks: dict[str, bool] = {}
    errors: list[str] = []

    if payload.get("insufficient") is True:
        raise InsufficientCompletion(str(payload.get("answer") or ""))

    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        checks["answer_present"] = False
        errors.append("answer_missing")
        answer = ""
    else:
        checks["answer_present"] = True
        answer = answer.strip()

    sentence_count = count_sentences(answer)
    checks["sentence_count"] = 0 < sentence_count <= max_sentences
    if not checks["sentence_count"]:
        errors.append(f"sentence_count_{sentence_count}_exceeds_{max_sentences}")

    citation_index = payload.get("citation_index")
    if isinstance(citation_index, bool) or not isinstance(citation_index, int):
        checks["citation_index"] = False
        errors.append("citation_index_missing_or_not_integer")
        citation_index = 0
    elif not 1 <= citation_index <= len(chunks):
        checks["citation_index"] = False
        errors.append("citation_index_out_of_range")
    else:
        checks["citation_index"] = True

    chunk = chunks[citation_index - 1] if checks.get("citation_index") else None

    used_chunk_ids = payload.get("used_chunk_ids")
    if (
        not isinstance(used_chunk_ids, list)
        or not used_chunk_ids
        or not all(isinstance(item, str) and item for item in used_chunk_ids)
    ):
        checks["used_chunk_ids"] = False
        errors.append("used_chunk_ids_missing_or_invalid")
        used_ids: tuple[str, ...] = ()
    else:
        used_ids = tuple(used_chunk_ids)
        checks["used_chunk_ids"] = True

    if chunk is not None:
        chunk_id = str(getattr(chunk, "chunk_id", "") or "")
        if not chunk_id or chunk_id not in used_ids:
            checks["cited_chunk_in_used_ids"] = False
            errors.append("cited_chunk_not_in_used_chunk_ids")
        else:
            checks["cited_chunk_in_used_ids"] = True

        source_url = str(getattr(chunk, "source_url", "") or "")
        known_urls = {
            str(getattr(item, "source_url", "") or "") for item in chunks
        }
        checks["citation_in_retrieved_chunks"] = bool(
            source_url and source_url in known_urls
        )
        if not checks["citation_in_retrieved_chunks"]:
            errors.append("citation_url_not_in_retrieved_chunks")

        last_updated = str(getattr(chunk, "scraped_at", "") or "")
        checks["last_updated"] = bool(last_updated and _is_iso_timestamp(last_updated))
        if not checks["last_updated"]:
            errors.append("last_updated_missing_or_invalid")
    else:
        source_url = ""
        last_updated = ""
        checks["cited_chunk_in_used_ids"] = False
        checks["citation_in_retrieved_chunks"] = False
        checks["last_updated"] = False

    checks["single_citation"] = not bool(_URL.search(answer))
    if not checks["single_citation"]:
        errors.append("answer_contains_url")

    checks["no_advice_language"] = not contains_advice_language(answer)
    if not checks["no_advice_language"]:
        errors.append("advice_language_in_answer")

    checks["no_pii"] = not contains_pii(answer)
    if not checks["no_pii"]:
        errors.append("pii_in_answer")

    if chunk is not None:
        cited_text = str(getattr(chunk, "text", "") or "")
        missing_numbers = extract_numbers(answer) - extract_numbers(cited_text)
        checks["numbers_grounded"] = not missing_numbers
        if missing_numbers:
            errors.append(
                "numbers_not_in_cited_chunk:"
                + ",".join(sorted(missing_numbers))
            )
    else:
        checks["numbers_grounded"] = False

    checks["disclaimer"] = bool(disclaimer and disclaimer.strip())
    if not checks["disclaimer"]:
        errors.append("disclaimer_missing")

    if errors:
        raise ValidationError(errors, checks)

    assert chunk is not None  # guaranteed when citation checks passed
    return ValidatedAnswer(
        answer=answer,
        citation_index=citation_index,
        citation_url=source_url,
        citation_title=str(getattr(chunk, "source_title", "") or ""),
        last_updated=last_updated,
        used_chunk_ids=used_ids,
        sentence_count=sentence_count,
        checks=checks,
    )
