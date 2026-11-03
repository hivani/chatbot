"""PII detection and redaction for the query edge.

The guardrail runs before retrieval, prompting, or artifact writes. Only the
redacted query is ever persisted; the original value is never echoed, logged,
embedded, or sent to a provider.

Patterns follow ``implementation.md`` §8.2. Matches are collected in priority
order and overlapping spans are ignored so one value is not redacted twice
(for example, the last ten digits of a 12-digit Aadhaar number are not also
treated as a phone number).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

PLACEHOLDERS: dict[str, str] = {
    "email": "[REDACTED_EMAIL]",
    "pan": "[REDACTED_PAN]",
    "aadhaar": "[REDACTED_AADHAAR]",
    "phone": "[REDACTED_PHONE]",
    "otp": "[REDACTED_OTP]",
    "account": "[REDACTED_ACCOUNT]",
}


@dataclass(frozen=True)
class PIIMatch:
    """One detected PII span in the original text."""

    type: str
    start: int
    end: int
    placeholder: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class PIIResult:
    """Redacted text plus the PII categories that were found."""

    original: str
    text: str
    matches: tuple[PIIMatch, ...]

    @property
    def detected(self) -> bool:
        return bool(self.matches)

    @property
    def types(self) -> tuple[str, ...]:
        seen: list[str] = []
        for match in self.matches:
            if match.type not in seen:
                seen.append(match.type)
        return tuple(seen)

    def to_dict(self) -> dict:
        """Decision payload safe to write to an artifact."""

        return {
            "pii_detected": self.detected,
            "pii_types": list(self.types),
            "redacted_query": self.text,
            "matches": [match.to_dict() for match in self.matches],
        }


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_PAN = re.compile(r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b")

# OTP is only PII when it appears near an OTP phrase. The value group keeps the
# surrounding words intact while redacting the digits.
_OTP_AFTER = re.compile(
    r"(?i)(?:\botp\b|one[-\s]?time\s+password)[^\d]{0,24}"
    r"(?P<value>\d{4,8})(?!\d)"
)
_OTP_BEFORE = re.compile(
    r"(?i)(?<!\d)(?P<value>\d{4,8})(?!\d)[^\d]{0,24}"
    r"(?:\botp\b|one[-\s]?time\s+password)"
)

# Account numbers need context so a 12-digit Aadhaar number is classified
# correctly and ordinary dates/amounts are left alone.
_ACCOUNT_AFTER = re.compile(
    r"(?i)(?:\ba/?c\b|account\s*(?:no\.?|number)?)[^\d]{0,24}"
    r"(?P<value>\d[\d\s-]{7,20}\d)"
)
_ACCOUNT_BEFORE = re.compile(
    r"(?i)(?P<value>\d[\d\s-]{7,20}\d)[^\d]{0,24}"
    r"(?:\ba/?c\b|account\s*(?:no\.?|number)?)"
)

_AADHAAR = re.compile(
    r"(?<!\d)(?P<value>\d{4}[\s-]?\d{4}[\s-]?\d{4})(?!\d)"
)
_PHONE = re.compile(
    r"(?<!\d)(?P<value>(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9})(?!\d)"
)

# Order matters: contextual account/OTP checks run before the bare number
# patterns so the most specific label wins.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", _EMAIL),
    ("pan", _PAN),
    ("otp", _OTP_AFTER),
    ("otp", _OTP_BEFORE),
    ("account", _ACCOUNT_AFTER),
    ("account", _ACCOUNT_BEFORE),
    ("aadhaar", _AADHAAR),
    ("phone", _PHONE),
)


def _value_span(match: re.Match[str]) -> tuple[int, int]:
    value = match.groupdict().get("value")
    if value:
        return match.span("value")
    return match.span()


def _overlaps(span: tuple[int, int], existing: Iterable[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and end > other_start for other_start, other_end in existing)


def find_pii(text: str) -> tuple[PIIMatch, ...]:
    """Return non-overlapping PII matches in start order."""

    if not text:
        return ()

    accepted: list[PIIMatch] = []
    spans: list[tuple[int, int]] = []

    for pii_type, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            span = _value_span(match)
            if span[0] == span[1] or _overlaps(span, spans):
                continue
            spans.append(span)
            accepted.append(
                PIIMatch(
                    type=pii_type,
                    start=span[0],
                    end=span[1],
                    placeholder=PLACEHOLDERS[pii_type],
                )
            )

    accepted.sort(key=lambda item: item.start)
    return tuple(accepted)


def redact_pii(text: str) -> PIIResult:
    """Detect and replace PII in ``text`` with typed placeholders."""

    matches = find_pii(text)
    if not matches:
        return PIIResult(original=text, text=text, matches=())

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start])
        pieces.append(match.placeholder)
        cursor = match.end
    pieces.append(text[cursor:])

    return PIIResult(original=text, text="".join(pieces), matches=matches)


def contains_pii(text: str) -> bool:
    """Convenience check used by tests and eval scans."""

    return bool(find_pii(text))
