"""Pre-retrieval intent classification.

The classifier is deliberately rule-based and deterministic. It runs after PII
detection and short-circuits advice and performance questions. Anything that
is not clearly advice or performance is allowed to continue to retrieval and
the sufficiency check, which is the final authority on whether the corpus can
answer the question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Intent = Literal["advice", "performance", "factual", "neutral"]


@dataclass(frozen=True)
class IntentDecision:
    """Guardrail decision for one sanitized query."""

    intent: Intent
    reasons: tuple[str, ...] = ()
    factual_terms: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.intent == "advice":
            return "refused_advice"
        if self.intent == "performance":
            return "refused_performance"
        return "allow"

    @property
    def allowed(self) -> bool:
        return self.intent in {"factual", "neutral"}

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "decision": self.status,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "factual_terms": list(self.factual_terms),
        }


# Phrases that explicitly take advice out of the question. They are removed
# before classification so a factual question that says "I'm not asking
# whether to buy" is not refused as advice.
_NEGATED_ADVICE = re.compile(
    r"(?i)"
    r"(?:\b(?:i'?m|i am|we are|we're)\s+)?"
    r"\b(?:not|n't)\s+"
    r"(?:asking|looking|requesting|seeking)\s+"
    r"(?:(?:for|about|whether|if)\s+)?"
    r"(?:to\s+)?"
    r"(?:buy|sell|hold|invest(?:ing)?|advice|a recommendation|recommendations?|"
    r"which\s+fund|the\s+best\s+fund)\b"
)
_NEGATED_RECOMMENDATION = re.compile(
    r"(?i)\b(?:do\s+not|don't|dont|never)\s+"
    r"(?:recommend|advise|suggest|tell\s+me\s+what\s+to\s+(?:buy|sell|hold))\b"
)

_ADVICE_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("should_i", re.compile(r"(?i)\bshould\s+(?:i|we)\b")),
    ("buy_sell_hold", re.compile(r"(?i)\b(?:buy|sell|hold)\b")),
    ("invest_in", re.compile(r"(?i)\binvest(?:ing|ment)?\s+in\b")),
    ("recommend", re.compile(r"(?i)\brecommend\w*\b")),
    ("suggest", re.compile(r"(?i)\bsuggest\w*\b")),
    ("best_fund", re.compile(r"(?i)\bbest\s+(?:fund|scheme|investment|option)\b")),
    ("worth_it", re.compile(r"(?i)\bworth\s+(?:it|investing)\b")),
    ("portfolio", re.compile(r"(?i)\bportfolio\b")),
    ("which_fund", re.compile(r"(?i)\bwhich\s+(?:fund|scheme)\b")),
    ("which_best", re.compile(r"(?i)\bwhich\s+(?:is\s+)?(?:the\s+)?best\b")),
    ("safe_bet", re.compile(r"(?i)\bsafe\s+bet\b")),
    ("good_investment", re.compile(r"(?i)\b(?:good|bad)\s+investment\b")),
    ("good_fund", re.compile(r"(?i)\b(?:good|bad)\s+(?:fund|scheme)\b")),
)

_PERFORMANCE_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("returns", re.compile(r"(?i)\breturns?\b")),
    ("cagr", re.compile(r"(?i)\bcagr\b")),
    ("xirr", re.compile(r"(?i)\bxirr\b")),
    ("past_performance", re.compile(r"(?i)\bpast\s+performance\b")),
    ("compare_performance", re.compile(r"(?i)\bcompare\s+(?:the\s+)?performance\b")),
    ("profit", re.compile(r"(?i)\bprofit\b")),
    (
        "earnings_projection",
        re.compile(
            r"(?i)\bhow\s+much\s+(?:money\s+)?(?:will|would|can|could)\s+"
            r"(?:i|we)\s+(?:earn|make|get|receive)\b"
        ),
    ),
    (
        "one_year_return",
        re.compile(r"(?i)\b(?:1|one)[-\s]?year\s+returns?\b"),
    ),
)

_FACTUAL_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("expense_ratio", re.compile(r"(?i)\b(?:total\s+)?expense\s+ratio\b|\bter\b")),
    ("exit_load", re.compile(r"(?i)\b(?:exit|entry)\s+load\b|\bloads?\b")),
    ("sip", re.compile(r"(?i)\bsip\b|\bsystematic\s+investment\s+plan\b")),
    ("lock_in", re.compile(r"(?i)\block[\s-]?in\b")),
    ("riskometer", re.compile(r"(?i)\briskometer\b|\brisk\s+level")),
    ("benchmark", re.compile(r"(?i)\bbenchmarks?\b")),
    (
        "statement",
        re.compile(
            r"(?i)\bstatements?\b|\bcapital\s+gains?\b|\bcas\b|\bdownload\b"
        ),
    ),
)


def _strip_negated_advice(text: str) -> tuple[str, bool]:
    cleaned, first = _NEGATED_ADVICE.subn(" ", text)
    cleaned, second = _NEGATED_RECOMMENDATION.subn(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(), bool(first or second)


def _matches(
    text: str,
    signals: tuple[tuple[str, re.Pattern[str]], ...],
) -> tuple[str, ...]:
    return tuple(name for name, pattern in signals if pattern.search(text))


def classify_intent(text: str) -> IntentDecision:
    """Classify a PII-free query as advice, performance, factual, or neutral."""

    cleaned, negated = _strip_negated_advice(text or "")
    factual_terms = _matches(cleaned, _FACTUAL_SIGNALS)

    advice_reasons = _matches(cleaned, _ADVICE_SIGNALS)
    if advice_reasons:
        reasons = advice_reasons
        if negated:
            reasons = (*reasons, "negated_advice_context")
        return IntentDecision(
            intent="advice",
            reasons=reasons,
            factual_terms=factual_terms,
        )

    performance_reasons = _matches(cleaned, _PERFORMANCE_SIGNALS)
    if performance_reasons:
        return IntentDecision(
            intent="performance",
            reasons=performance_reasons,
            factual_terms=factual_terms,
        )

    if factual_terms:
        return IntentDecision(
            intent="factual",
            reasons=("factual_allowlist",),
            factual_terms=factual_terms,
        )

    return IntentDecision(intent="neutral", reasons=("no_strong_intent_signal",))
