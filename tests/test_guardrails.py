import pytest

from src.guardrails.intent import classify_intent
from src.guardrails.pii import contains_pii, find_pii, redact_pii


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected_type, placeholder",
    [
        ("My PAN is ABCDE1234F, what is the ELSS lock-in?", "pan", "[REDACTED_PAN]"),
        ("Call me on 9876543210", "phone", "[REDACTED_PHONE]"),
        ("Email me at a@b.com", "email", "[REDACTED_EMAIL]"),
        ("OTP is 123456", "otp", "[REDACTED_OTP]"),
        ("A/c 123456789012", "account", "[REDACTED_ACCOUNT]"),
        ("Aadhaar 1234 5678 9012", "aadhaar", "[REDACTED_AADHAAR]"),
        ("+91 98765 43210 is my number", "phone", "[REDACTED_PHONE]"),
    ],
)
def test_pii_is_detected_and_redacted(text, expected_type, placeholder):
    result = redact_pii(text)

    assert result.detected is True
    assert expected_type in result.types
    assert placeholder in result.text
    assert text not in result.text


def test_pii_decision_never_contains_the_original_value():
    result = redact_pii("PAN ABCDE1234F")
    decision = result.to_dict()

    assert decision["pii_detected"] is True
    assert decision["pii_types"] == ["pan"]
    assert "ABCDE1234F" not in str(decision)
    assert "original" not in decision


def test_pii_spans_do_not_overlap():
    matches = find_pii("Aadhaar 1234 5678 9012")

    assert len(matches) == 1
    assert matches[0].type == "aadhaar"


def test_non_pii_question_is_unchanged():
    text = "What is the expense ratio of HDFC Flexi Cap?"

    result = redact_pii(text)

    assert result.detected is False
    assert result.text == text
    assert result.types == ()
    assert contains_pii(text) is False


def test_pii_types_are_unique():
    result = redact_pii("Mail a@b.com or c@d.com")

    assert result.types == ("email",)
    assert result.text.count("[REDACTED_EMAIL]") == 2


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Should I buy HDFC ELSS?",
        "Which is the best HDFC fund?",
        "Is ELSS a good investment?",
        "Is HDFC Flexi Cap worth it?",
        "Recommend a fund for my portfolio",
        "Which fund should I hold?",
    ],
)
def test_advice_intent_is_refused(text):
    decision = classify_intent(text)

    assert decision.intent == "advice"
    assert decision.status == "refused_advice"
    assert decision.allowed is False


@pytest.mark.parametrize(
    "text",
    [
        "Compare 1-year returns of ELSS and Flexi Cap",
        "How much will I earn in 3 years?",
        "What is the CAGR of HDFC Mid Cap?",
        "Show me the past performance",
        "What profit will I make?",
    ],
)
def test_performance_intent_is_refused(text):
    decision = classify_intent(text)

    assert decision.intent == "performance"
    assert decision.status == "refused_performance"
    assert decision.allowed is False


@pytest.mark.parametrize(
    "text",
    [
        "What is the exit load on HDFC ELSS?",
        "ELSS lock-in?",
        "Minimum SIP for HDFC Flexi Cap?",
        "How do I download a capital gains statement?",
        "What is the riskometer level of HDFC Large Cap?",
        "I'm not asking whether to buy — what's the expense ratio?",
        "Don't recommend anything, just tell me the exit load",
    ],
)
def test_factual_or_negated_advice_is_allowed(text):
    decision = classify_intent(text)

    assert decision.allowed is True
    assert decision.status == "allow"
    assert decision.intent in {"factual", "neutral"}


def test_unclear_intent_is_allowed_for_sufficiency_to_decide():
    decision = classify_intent("Tell me about HDFC Mutual Fund")

    assert decision.intent == "neutral"
    assert decision.allowed is True


def test_advice_wins_over_performance():
    decision = classify_intent("Should I buy the fund with the best returns?")

    assert decision.intent == "advice"
    assert decision.reasons
