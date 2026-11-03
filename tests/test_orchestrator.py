from pathlib import Path

import pytest

from src.artifacts import list_artifacts, read_artifact, read_json_artifact
from src.config import load_settings
from src.ingest.loader import SourceSpec
from src.query.orchestrator import QueryOrchestrator
from src.rag.generator import Completion, GeneratorError
from src.rag.retriever import RetrievalResult, RetrievedChunk, Sufficiency
from src.rag.validator import count_sentences

ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
LOADS_URL = "https://www.mutualfundssahihai.com/en/what-are-loads"
EXPENSES_URL = "https://www.mutualfundssahihai.com/en/what-are-expenses-incurred-mutual-fund-scheme"
ELSS_TITLE = "HDFC ELSS Tax Saver Fund Direct Plan Growth"

ARTIFACTS = [
    "00_request.json",
    "01_guardrails.json",
    "02_retrieval.json",
    "03_prompt.txt",
    "04_completion.json",
    "05_response.json",
]


def _sources():
    return [
        SourceSpec(
            id="hdfc-elss",
            url=ELSS_URL,
            title=ELSS_TITLE,
            category="scheme",
            aliases=("HDFC ELSS", "ELSS Tax Saver", "ELSS"),
        ),
        SourceSpec(
            id="mf-loads",
            url=LOADS_URL,
            title="What are loads?",
            category="education",
            aliases=("load", "exit load"),
        ),
        SourceSpec(
            id="mf-expenses",
            url=EXPENSES_URL,
            title="What are the expenses incurred in a Mutual Fund scheme?",
            category="education",
            aliases=("expense ratio", "expenses"),
        ),
    ]


def _chunk():
    return RetrievedChunk(
        rank=1,
        chunk_id="hdfc-elss::overview::002",
        score=0.91,
        distance=0.09,
        text=(
            "HDFC ELSS Tax Saver Fund Direct Plan Growth — Overview (table).\n"
            "Expense ratio | 1.20%\n"
            "Exit load | Nil"
        ),
        doc_id="hdfc-elss",
        source_url=ELSS_URL,
        source_title=ELSS_TITLE,
        section="Overview",
        content_type="table",
        scraped_at="2026-11-02T07:03:13Z",
    )


def _retrieval(*, sufficient=True):
    chunk = _chunk()
    sufficiency = Sufficiency(
        sufficient=sufficient,
        reason=None if sufficient else "fact_not_in_results",
        top_score=0.91 if sufficient else 0.12,
        score_margin=0.2,
        detected_scheme_ids=("hdfc-elss",),
        detected_fact_types=("expense_ratio",),
        matching_scheme_chunk_ids=(chunk.chunk_id,),
        matching_fact_chunk_ids=(chunk.chunk_id,) if sufficient else (),
        suggested_url=ELSS_URL if sufficient else LOADS_URL,
    )
    return RetrievalResult(
        question="What is the expense ratio of HDFC ELSS?",
        embedding_model="fake-embedder",
        collection="groww_mf_faq",
        top_k=5,
        min_score=0.35,
        results=(chunk,) if sufficient else (),
        sufficiency=sufficiency,
    )


class FakeRetriever:
    def __init__(self, retrieval):
        self.retrieval = retrieval
        self.sources = _sources()
        self.calls = []

    def retrieve(self, question):
        self.calls.append(question)
        if isinstance(self.retrieval, Exception):
            raise self.retrieval
        return self.retrieval


class FakeGenerator:
    provider = "fake"
    model = "fake-v1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if not self.responses:
            raise AssertionError("FakeGenerator received an unexpected call")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return Completion(
            provider=self.provider,
            model=self.model,
            text=item,
            latency_ms=7,
            prompt_tokens=11,
            completion_tokens=7,
        )


def _answer_json(
    *,
    answer="The expense ratio is 1.20%.",
    citation_index=1,
    used_chunk_ids=("hdfc-elss::overview::002",),
    insufficient=False,
):
    import json

    return json.dumps(
        {
            "answer": answer,
            "citation_index": citation_index,
            "used_chunk_ids": list(used_chunk_ids),
            "insufficient": insufficient,
        }
    )


def _orchestrator(tmp_path, *, retrieval=None, responses=None):
    retriever = FakeRetriever(retrieval or _retrieval())
    generator = FakeGenerator(responses or [_answer_json()])
    orchestrator = QueryOrchestrator(
        settings=load_settings(),
        retriever=retriever,
        generator=generator,
        sources=_sources(),
        artifacts_root=tmp_path,
    )
    return orchestrator, retriever, generator


def _all_artifact_text(root, query_id):
    return "\n".join(
        (Path(root) / query_id / name).read_text(encoding="utf-8")
        for name in list_artifacts(root, query_id)
    )


# ---------------------------------------------------------------------------
# Answered
# ---------------------------------------------------------------------------


def test_answered_response_writes_all_six_artifacts(tmp_path):
    orchestrator, retriever, generator = _orchestrator(tmp_path)

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")
    payload = response.to_dict()

    assert payload["status"] == "answered"
    assert payload["answer"] == "The expense ratio is 1.20%."
    assert payload["citation"] == {"url": ELSS_URL, "title": ELSS_TITLE}
    assert payload["last_updated"] == "2026-11-02T07:03:13Z"
    assert payload["disclaimer"] == "Facts-only. No investment advice."
    assert payload["refusal_reason"] is None
    assert payload["validation"]["checks"]
    assert retriever.calls == ["What is the expense ratio of HDFC ELSS?"]
    assert len(generator.calls) == 1

    query_id = payload["query_id"]
    assert list_artifacts(tmp_path, query_id) == ARTIFACTS

    request = read_json_artifact(tmp_path, query_id, "00_request.json")
    guardrails = read_json_artifact(tmp_path, query_id, "01_guardrails.json")
    retrieval = read_json_artifact(tmp_path, query_id, "02_retrieval.json")
    prompt = read_artifact(tmp_path, query_id, "03_prompt.txt")
    completion = read_json_artifact(tmp_path, query_id, "04_completion.json")
    final = read_json_artifact(tmp_path, query_id, "05_response.json")

    assert request["query"] == "What is the expense ratio of HDFC ELSS?"
    assert request["pii_redacted"] is False
    assert guardrails["intent"] == "factual"
    assert guardrails["decision"] == "allow"
    assert retrieval["sufficient"] is True
    assert retrieval["results"][0]["chunk_id"] == "hdfc-elss::overview::002"
    assert ELSS_URL in prompt
    assert "CONTEXT" in prompt
    assert completion["provider"] == "fake"
    assert completion["attempts"][0]["attempt"] == 1
    assert final["status"] == "answered"


def test_validation_retry_is_used_once_then_succeeds(tmp_path):
    bad = _answer_json(answer="One. Two. Three. Four.")
    orchestrator, _retriever, generator = _orchestrator(
        tmp_path,
        responses=[bad, _answer_json()],
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "answered"
    assert len(generator.calls) == 2
    second_messages = generator.calls[1]["messages"]
    assert any(
        "failed validation" in message["content"] for message in second_messages
    )

    prompt = read_artifact(
        tmp_path, response.query_id, "03_prompt.txt"
    )
    assert "=== attempt 1 ===" in prompt
    assert "=== attempt 2 ===" in prompt


def test_two_validation_failures_return_safe_error_not_model_text(tmp_path):
    bad = _answer_json(answer="One. Two. Three. Four.")
    orchestrator, _retriever, _generator = _orchestrator(
        tmp_path,
        responses=[bad, bad],
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "error"
    assert response.answer != "One. Two. Three. Four."
    assert response.citation is not None
    assert response.citation.url == ELSS_URL
    assert response.refusal_reason == "validation_failed"

    completion = read_json_artifact(
        tmp_path, response.query_id, "04_completion.json"
    )
    assert len(completion["attempts"]) == 2
    assert len(completion["validation"]) == 2


def test_generated_advice_is_replaced_with_a_refusal(tmp_path):
    orchestrator, _retriever, _generator = _orchestrator(
        tmp_path,
        responses=[
            _answer_json(answer="You should buy this fund for 1.20%."),
            _answer_json(answer="You should buy this fund for 1.20%."),
        ],
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "refused_advice"
    assert "You should buy" not in response.answer
    assert response.refusal_reason == "validation_failed"


def test_generator_error_returns_safe_error_envelope(tmp_path):
    orchestrator, _retriever, _generator = _orchestrator(
        tmp_path,
        responses=[GeneratorError("provider timeout")],
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "error"
    assert response.refusal_reason == "generation_failed"
    assert response.citation is not None
    completion = read_json_artifact(
        tmp_path, response.query_id, "04_completion.json"
    )
    assert completion["status"] == "error"
    assert completion["error"] == "GeneratorError"


def test_retrieval_error_returns_safe_error_envelope(tmp_path):
    orchestrator, _retriever, _generator = _orchestrator(
        tmp_path,
        retrieval=RuntimeError("store unavailable"),
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "error"
    assert response.refusal_reason == "retrieval_failed"
    retrieval = read_json_artifact(
        tmp_path, response.query_id, "02_retrieval.json"
    )
    assert retrieval["error"] == "RuntimeError"


# ---------------------------------------------------------------------------
# Refusals and sufficiency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, status",
    [
        ("Should I buy HDFC ELSS?", "refused_advice"),
        ("Which is the best HDFC fund?", "refused_advice"),
        ("Compare 1-year returns of ELSS and Flexi Cap", "refused_performance"),
        ("How much will I earn in 3 years?", "refused_performance"),
    ],
)
def test_intent_refusals_never_call_retrieval_or_generation(tmp_path, question, status):
    orchestrator, retriever, generator = _orchestrator(tmp_path)

    response = orchestrator.answer(question)

    assert response.status == status
    assert retriever.calls == []
    assert generator.calls == []
    assert response.refusal_reason in {"advice", "performance"}
    assert response.citation is not None
    assert count_sentences(response.answer) <= 3
    assert "http" not in response.answer
    assert list_artifacts(tmp_path, response.query_id) == ARTIFACTS


@pytest.mark.parametrize(
    "question",
    [
        "My PAN is ABCDE1234F, what is the ELSS lock-in?",
        "Call me on 9876543210",
        "Email me at a@b.com",
        "OTP is 123456",
        "A/c 123456789012",
    ],
)
def test_pii_is_refused_and_never_persisted(tmp_path, question):
    orchestrator, retriever, generator = _orchestrator(tmp_path)

    response = orchestrator.answer(question)

    assert response.status == "refused_pii"
    assert retriever.calls == []
    assert generator.calls == []

    artifacts = _all_artifact_text(tmp_path, response.query_id)
    for value in (
        "ABCDE1234F",
        "9876543210",
        "a@b.com",
        "123456",
        "123456789012",
    ):
        if value in question:
            assert value not in artifacts

    request = read_json_artifact(
        tmp_path, response.query_id, "00_request.json"
    )
    assert "[REDACTED_" in request["query"]


def test_pii_is_checked_before_advice(tmp_path):
    orchestrator, retriever, generator = _orchestrator(tmp_path)

    response = orchestrator.answer("My PAN is ABCDE1234F, should I buy HDFC ELSS?")

    assert response.status == "refused_pii"
    assert retriever.calls == []
    assert generator.calls == []


@pytest.mark.parametrize(
    "question",
    [
        "Should I buy HDFC ELSS?",
        "Compare 1-year returns of ELSS and Flexi Cap",
        "My PAN is ABCDE1234F, what is the lock-in?",
    ],
)
def test_refusals_link_an_official_education_page(tmp_path, question):
    orchestrator, _retriever, _generator = _orchestrator(tmp_path)

    response = orchestrator.answer(question)

    assert response.status != "answered"
    assert response.citation is not None
    assert response.citation.url == LOADS_URL
    assert response.citation.title == "What are loads?"
    assert response.last_updated is None


def test_insufficient_context_returns_closest_official_page(tmp_path):
    orchestrator, retriever, generator = _orchestrator(
        tmp_path,
        retrieval=_retrieval(sufficient=False),
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "insufficient_context"
    assert response.refusal_reason == "fact_not_in_results"
    assert response.citation is not None
    assert response.citation.to_dict() == {
        "url": LOADS_URL,
        "title": "What are loads?",
    }
    assert retriever.calls
    assert generator.calls == []

    retrieval = read_json_artifact(
        tmp_path, response.query_id, "02_retrieval.json"
    )
    assert retrieval["sufficient"] is False
    prompt = read_artifact(tmp_path, response.query_id, "03_prompt.txt")
    assert "Not sent: insufficient_context" in prompt


def test_model_reported_insufficient_is_mapped_to_insufficient_context(tmp_path):
    orchestrator, _retriever, _generator = _orchestrator(
        tmp_path,
        responses=[
            _answer_json(
                answer="The sources do not say.",
                citation_index=1,
                insufficient=True,
            )
        ],
    )

    response = orchestrator.answer("What is the expense ratio of HDFC ELSS?")

    assert response.status == "insufficient_context"
    assert response.refusal_reason == "model_reported_insufficient"
    assert response.answer != "The sources do not say."


def test_empty_question_is_rejected(tmp_path):
    orchestrator, _retriever, _generator = _orchestrator(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        orchestrator.answer("   ")
