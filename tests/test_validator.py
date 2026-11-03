from types import SimpleNamespace

import pytest

from src.rag.prompts import DISCLAIMER
from src.rag.validator import (
    CompletionParseError,
    InsufficientCompletion,
    ValidationError,
    count_sentences,
    extract_numbers,
    parse_json_object,
    validate_completion,
)


def _chunk(
    *,
    chunk_id="hdfc-elss::overview::002",
    text="HDFC ELSS — Overview. Expense ratio | 1.20%\nExit load | Nil",
    source_url="https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    source_title="HDFC ELSS Tax Saver Fund Direct Plan Growth",
    scraped_at="2026-11-02T07:03:13Z",
):
    return SimpleNamespace(
        chunk_id=chunk_id,
        text=text,
        source_url=source_url,
        source_title=source_title,
        section="Overview",
        scraped_at=scraped_at,
    )


def _payload(**overrides):
    payload = {
        "answer": "The expense ratio is 1.20%.",
        "citation_index": 1,
        "used_chunk_ids": ["hdfc-elss::overview::002"],
        "insufficient": False,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Parsing and counting
# ---------------------------------------------------------------------------


def test_parse_json_object_accepts_markdown_fences():
    payload = parse_json_object(
        "```json\n"
        '{"answer": "ok", "citation_index": 1, "used_chunk_ids": ["x"], '
        '"insufficient": false}\n'
        "```"
    )

    assert payload["answer"] == "ok"


def test_parse_json_object_rejects_non_json():
    with pytest.raises(CompletionParseError, match="JSON"):
        parse_json_object("I think the answer is 42.")


def test_count_sentences_handles_decimals_and_dates():
    assert count_sentences("The NAV is ₹1,434.92 as of 30 Oct '26.") == 1
    assert count_sentences("One. Two. Three.") == 3
    assert count_sentences("") == 0


def test_extract_numbers_normalizes_commas_and_trailing_zeros():
    assert extract_numbers("Expense ratio 1.20%, NAV ₹1,434.92") == {
        "1.2%",
        "1434.92",
    }


# ---------------------------------------------------------------------------
# Valid answers
# ---------------------------------------------------------------------------


def test_valid_answer_resolves_citation_and_last_updated():
    result = validate_completion(_payload(), [_chunk()])

    assert result.answer == "The expense ratio is 1.20%."
    assert result.citation_index == 1
    assert result.citation_url.startswith("https://groww.in/")
    assert result.citation_title == "HDFC ELSS Tax Saver Fund Direct Plan Growth"
    assert result.last_updated == "2026-11-02T07:03:13Z"
    assert result.sentence_count == 1
    assert all(result.checks.values())


def test_disclaimer_is_checked_against_the_response_contract():
    with pytest.raises(ValidationError, match="disclaimer_missing"):
        validate_completion(_payload(), [_chunk()], disclaimer="")


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_more_than_three_sentences_is_rejected():
    payload = _payload(answer="One. Two. Three. Four.")

    with pytest.raises(ValidationError, match="sentence_count"):
        validate_completion(payload, [_chunk()])


def test_citation_index_zero_is_rejected():
    with pytest.raises(ValidationError, match="citation_index"):
        validate_completion(_payload(citation_index=0), [_chunk()])


def test_citation_index_beyond_retrieved_chunks_is_rejected():
    with pytest.raises(ValidationError, match="citation_index_out_of_range"):
        validate_completion(_payload(citation_index=2), [_chunk()])


def test_cited_chunk_must_be_in_used_chunk_ids():
    payload = _payload(used_chunk_ids=["some-other-chunk"])

    with pytest.raises(ValidationError, match="cited_chunk_not_in_used_chunk_ids"):
        validate_completion(payload, [_chunk()])


def test_advice_language_is_rejected():
    payload = _payload(answer="You should buy this fund now.")

    with pytest.raises(ValidationError, match="advice_language"):
        validate_completion(payload, [_chunk()])


@pytest.mark.parametrize(
    "answer",
    [
        "You cannot sell or redeem units before the three-year lock-in ends.",
        "You must remain invested for three years to avoid the lock-in.",
        "You can redeem the units after the lock-in period.",
    ],
)
def test_factual_restriction_language_is_not_treated_as_advice(answer):
    result = validate_completion(_payload(answer=answer), [_chunk()])

    assert result.checks["no_advice_language"] is True
    assert result.answer == answer


def test_url_written_by_the_model_is_rejected():
    payload = _payload(
        answer="See https://example.com for the expense ratio of 1.20%."
    )

    with pytest.raises(ValidationError, match="answer_contains_url"):
        validate_completion(payload, [_chunk()])


def test_number_absent_from_cited_chunk_is_rejected():
    payload = _payload(answer="The expense ratio is 2.50%.")

    with pytest.raises(ValidationError, match="numbers_not_in_cited_chunk"):
        validate_completion(payload, [_chunk()])


def test_pii_in_answer_is_rejected():
    payload = _payload(answer="Email a@b.com for the 1.20% expense ratio.")

    with pytest.raises(ValidationError, match="pii_in_answer"):
        validate_completion(payload, [_chunk()])


def test_missing_or_invalid_scraped_at_is_rejected():
    chunk = _chunk(scraped_at="")

    with pytest.raises(ValidationError, match="last_updated"):
        validate_completion(_payload(), [chunk])


def test_model_reported_insufficient_is_raised_separately():
    payload = _payload(insufficient=True, answer="The sources do not say.")

    with pytest.raises(InsufficientCompletion):
        validate_completion(payload, [_chunk()])


def test_empty_answer_is_rejected():
    with pytest.raises(ValidationError, match="answer_missing"):
        validate_completion(_payload(answer="  "), [_chunk()])
