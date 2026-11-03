"""Query orchestration: guardrails → retrieval → generation → validation.

Every call produces one ``artifacts/<query_id>/`` directory with all six stage
snapshots. Only the redacted query is written. The CLI and the Streamlit app
both use this module, so they share exactly the same control flow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from src.artifacts import ArtifactWriter, new_query_id
from src.config import PROJECT_ROOT, Settings, load_settings
from src.guardrails.intent import IntentDecision, classify_intent
from src.guardrails.pii import redact_pii
from src.ingest.loader import SourceSpec, load_sources
from src.rag.generator import (
    Completion,
    Generator,
    GeneratorError,
    build_generator,
)
from src.rag.prompts import (
    build_messages,
    build_retry_messages,
    refusal_message,
    render_messages,
)
from src.rag.retriever import (
    FACT_SOURCE_IDS,
    RetrievalResult,
    Retriever,
    detect_fact_types,
    detect_schemes,
)
from src.rag.validator import (
    CompletionParseError,
    InsufficientCompletion,
    ValidatedAnswer,
    ValidationError,
    parse_json_object,
    validate_completion,
)

ARTIFACT_FILENAMES: dict[str, str] = {
    "request": "00_request.json",
    "guardrails": "01_guardrails.json",
    "retrieval": "02_retrieval.json",
    "prompt": "03_prompt.txt",
    "completion": "04_completion.json",
    "response": "05_response.json",
}

REFUSAL_STATUSES = {
    "refused_pii",
    "refused_advice",
    "refused_performance",
    "insufficient_context",
    "error",
}


@dataclass(frozen=True)
class Citation:
    url: str
    title: str

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "title": self.title}


@dataclass(frozen=True)
class QueryResponse:
    """User-facing answer envelope (also written as ``05_response.json``)."""

    query_id: str
    status: str
    query: str
    answer: str
    citation: Citation | None
    last_updated: str | None
    disclaimer: str
    refusal_reason: str | None
    stage_artifacts: dict[str, str]
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "status": self.status,
            "query": self.query,
            "answer": self.answer,
            "citation": self.citation.to_dict() if self.citation else None,
            "last_updated": self.last_updated,
            "disclaimer": self.disclaimer,
            "refusal_reason": self.refusal_reason,
            "stage_artifacts": dict(self.stage_artifacts),
            "validation": self.validation,
        }


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _config_hash(settings: Settings) -> str:
    """Stable hash of non-secret configuration used for this query."""

    snapshot = {
        "app": {
            "disclaimer": settings.app.disclaimer,
            "max_answer_sentences": settings.app.max_answer_sentences,
        },
        "embedding": settings.embedding.model_dump(mode="json"),
        "chunking": settings.chunking.model_dump(mode="json"),
        "vector_store": {
            "collection": settings.vector_store.collection,
            "distance": settings.vector_store.distance,
        },
        "retrieval": settings.retrieval.model_dump(mode="json"),
        "llm": {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens,
        },
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class QueryOrchestrator:
    """Run one question through every query-time stage."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        retriever: Any | None = None,
        generator: Generator | None = None,
        sources: Sequence[SourceSpec] | None = None,
        artifacts_root: str | Path | None = None,
    ):
        self.settings = settings or load_settings()

        if sources is not None:
            self.sources = list(sources)
        elif retriever is not None and getattr(retriever, "sources", None):
            self.sources = list(retriever.sources)
        else:
            self.sources = load_sources(self.settings.paths.sources)

        self.retriever = retriever or Retriever(
            settings=self.settings,
            sources=self.sources,
        )
        self.generator = generator or build_generator(
            self.settings,
            allow_offline_fallback=True,
        )
        self.artifacts_root = Path(
            artifacts_root or self.settings.paths.artifacts_dir
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def answer(self, question: str) -> QueryResponse:
        """Answer one question and write all six artifacts."""

        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question must not be empty")

        query_id = new_query_id()
        writer = ArtifactWriter(self.artifacts_root, query_id)
        received_at = _utc_now()

        pii = redact_pii(question.strip())
        safe_query = pii.text
        writer.write_json(
            "00_request.json",
            {
                "query_id": query_id,
                "query": safe_query,
                "received_at": received_at,
                "config_hash": _config_hash(self.settings),
                "pii_redacted": pii.detected,
            },
        )

        # 1. PII short-circuits before any retrieval, prompt, or provider call.
        if pii.detected:
            writer.write_json(
                "01_guardrails.json",
                {
                    "pii_detected": True,
                    "pii_types": list(pii.types),
                    "redacted_query": safe_query,
                    "intent": "blocked",
                    "decision": "refused_pii",
                    "allowed": False,
                    "reasons": ["pii_detected"],
                },
            )
            return self._refuse(
                writer,
                query_id,
                safe_query,
                "refused_pii",
                "pii_detected",
            )

        # 2. Advice and performance short-circuit before retrieval.
        intent = classify_intent(safe_query)
        writer.write_json(
            "01_guardrails.json",
            {
                "pii_detected": False,
                "pii_types": [],
                "redacted_query": safe_query,
                **intent.to_dict(),
            },
        )
        if intent.intent in {"advice", "performance"}:
            return self._refuse(
                writer,
                query_id,
                safe_query,
                intent.status,
                intent.intent,
                retrieval=None,
            )

        # 3. Retrieval + sufficiency.
        try:
            retrieval = self.retriever.retrieve(safe_query)
        except Exception as exc:  # noqa: BLE001 - return a safe error envelope
            writer.write_json(
                "02_retrieval.json",
                {
                    "query": safe_query,
                    "skipped": False,
                    "error": type(exc).__name__,
                },
            )
            return self._refuse(
                writer,
                query_id,
                safe_query,
                "error",
                "retrieval_failed",
                retrieval=None,
            )

        writer.write_json("02_retrieval.json", retrieval.to_dict())

        if not retrieval.sufficient:
            return self._refuse(
                writer,
                query_id,
                safe_query,
                "insufficient_context",
                retrieval.sufficiency.reason or "insufficient_context",
                retrieval=retrieval,
            )

        return self._generate_and_validate(
            writer,
            query_id,
            safe_query,
            retrieval,
        )

    # ------------------------------------------------------------------
    # Generation and validation
    # ------------------------------------------------------------------

    def _generate_and_validate(
        self,
        writer: ArtifactWriter,
        query_id: str,
        safe_query: str,
        retrieval: RetrievalResult,
    ) -> QueryResponse:
        chunks = list(retrieval.results)
        preferred = retrieval.preferred_chunk
        preferred_index = 1
        if preferred is not None:
            for index, chunk in enumerate(chunks, start=1):
                if chunk.chunk_id == preferred.chunk_id:
                    preferred_index = index
                    break

        fact_types = retrieval.sufficiency.detected_fact_types
        messages = build_messages(safe_query, chunks)
        prompt_attempts: list[str] = []
        completion_records: list[dict[str, Any]] = []
        validation_log: list[dict[str, Any]] = []
        last_completion: Completion | None = None
        final_errors: tuple[str, ...] = ()

        for attempt in (1, 2):
            if attempt == 2:
                messages = build_retry_messages(messages, final_errors)
            prompt_attempts.append(
                f"=== attempt {attempt} ===\n{render_messages(messages)}"
            )

            try:
                completion = self.generator.generate(
                    messages,
                    chunks=chunks,
                    question=safe_query,
                    preferred_index=preferred_index,
                    fact_types=fact_types,
                )
            except GeneratorError as exc:
                return self._refuse(
                    writer,
                    query_id,
                    safe_query,
                    "error",
                    "generation_failed",
                    retrieval=retrieval,
                    prompt_text="\n\n".join(prompt_attempts),
                    completion_payload={
                        "status": "error",
                        "error": type(exc).__name__,
                        "attempts": completion_records,
                    },
                )

            last_completion = completion
            record = completion.to_dict()
            record["attempt"] = attempt
            completion_records.append(record)

            try:
                payload = parse_json_object(completion.text)
                result = validate_completion(
                    payload,
                    chunks,
                    max_sentences=self.settings.app.max_answer_sentences,
                    disclaimer=self.settings.app.disclaimer,
                )
            except InsufficientCompletion:
                validation_log.append(
                    {
                        "attempt": attempt,
                        "errors": ["model_reported_insufficient"],
                        "checks": {},
                    }
                )
                return self._refuse(
                    writer,
                    query_id,
                    safe_query,
                    "insufficient_context",
                    "model_reported_insufficient",
                    retrieval=retrieval,
                    prompt_text="\n\n".join(prompt_attempts),
                    completion_payload=self._completion_payload(
                        last_completion, completion_records, validation_log
                    ),
                )
            except (CompletionParseError, ValidationError) as exc:
                if isinstance(exc, ValidationError):
                    errors = exc.errors
                    checks = exc.checks
                else:
                    errors = (str(exc),)
                    checks = {}
                final_errors = tuple(errors)
                validation_log.append(
                    {
                        "attempt": attempt,
                        "errors": list(errors),
                        "checks": checks,
                    }
                )
                continue

            validation_log.append(
                {
                    "attempt": attempt,
                    "errors": [],
                    "checks": result.checks,
                }
            )
            return self._answered(
                writer,
                query_id,
                safe_query,
                result,
                retrieval=retrieval,
                prompt_text="\n\n".join(prompt_attempts),
                completion_payload=self._completion_payload(
                    completion, completion_records, validation_log
                ),
            )

        # Both attempts failed. Return a deterministic safe envelope, never the
        # unvalidated model text.
        status = (
            "refused_advice"
            if any("advice_language" in error for error in final_errors)
            else "error"
        )
        return self._refuse(
            writer,
            query_id,
            safe_query,
            status,
            "validation_failed",
            retrieval=retrieval,
            prompt_text="\n\n".join(prompt_attempts),
            completion_payload=self._completion_payload(
                last_completion, completion_records, validation_log
            ),
        )

    @staticmethod
    def _completion_payload(
        completion: Completion | None,
        attempts: Sequence[dict[str, Any]],
        validation_log: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "attempts": list(attempts),
            "validation": list(validation_log),
        }
        if completion is not None:
            payload.update(
                {
                    "provider": completion.provider,
                    "model": completion.model,
                    "latency_ms": completion.latency_ms,
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                    "raw_output": completion.text,
                }
            )
        return payload

    # ------------------------------------------------------------------
    # Response construction
    # ------------------------------------------------------------------

    def _stage_paths(self, query_id: str) -> dict[str, str]:
        paths: dict[str, str] = {}
        for key, name in ARTIFACT_FILENAMES.items():
            absolute = self.artifacts_root / query_id / name
            try:
                paths[key] = str(absolute.relative_to(PROJECT_ROOT))
            except ValueError:
                paths[key] = str(absolute)
        return paths

    def _answered(
        self,
        writer: ArtifactWriter,
        query_id: str,
        safe_query: str,
        validated: ValidatedAnswer,
        *,
        retrieval: RetrievalResult,
        prompt_text: str,
        completion_payload: dict[str, Any],
    ) -> QueryResponse:
        response = QueryResponse(
            query_id=query_id,
            status="answered",
            query=safe_query,
            answer=validated.answer,
            citation=Citation(
                url=validated.citation_url,
                title=validated.citation_title,
            ),
            last_updated=validated.last_updated,
            disclaimer=self.settings.app.disclaimer,
            refusal_reason=None,
            stage_artifacts=self._stage_paths(query_id),
            validation={
                "sentence_count": validated.sentence_count,
                "citation_index": validated.citation_index,
                "used_chunk_ids": list(validated.used_chunk_ids),
                "checks": validated.checks,
            },
        )
        return self._finalize(
            writer,
            response,
            retrieval=retrieval,
            prompt_text=prompt_text,
            completion_payload=completion_payload,
        )

    def _refuse(
        self,
        writer: ArtifactWriter,
        query_id: str,
        safe_query: str,
        status: str,
        reason: str,
        *,
        retrieval: RetrievalResult | None = None,
        prompt_text: str | None = None,
        completion_payload: dict[str, Any] | None = None,
    ) -> QueryResponse:
        url = self._official_url(
            safe_query,
            retrieval,
            prefer_education=status
            in {"refused_pii", "refused_advice", "refused_performance"},
        )
        response = QueryResponse(
            query_id=query_id,
            status=status,
            query=safe_query,
            answer=refusal_message(status),
            citation=self._citation_for_url(url, retrieval),
            last_updated=None,
            disclaimer=self.settings.app.disclaimer,
            refusal_reason=reason,
            stage_artifacts=self._stage_paths(query_id),
            validation=None,
        )
        return self._finalize(
            writer,
            response,
            retrieval=retrieval,
            prompt_text=prompt_text,
            completion_payload=completion_payload,
        )

    def _finalize(
        self,
        writer: ArtifactWriter,
        response: QueryResponse,
        *,
        retrieval: RetrievalResult | None = None,
        prompt_text: str | None = None,
        completion_payload: dict[str, Any] | None = None,
    ) -> QueryResponse:
        """Write any missing stage artifacts and the final response."""

        if not writer.path("02_retrieval.json").exists():
            writer.write_json(
                "02_retrieval.json",
                (
                    retrieval.to_dict()
                    if retrieval is not None
                    else {"skipped": True, "reason": response.status}
                ),
            )
        if not writer.path("03_prompt.txt").exists():
            writer.write_text(
                "03_prompt.txt",
                prompt_text
                if prompt_text is not None
                else f"Not sent: {response.status}.\n",
            )
        if not writer.path("04_completion.json").exists():
            writer.write_json(
                "04_completion.json",
                (
                    completion_payload
                    if completion_payload is not None
                    else {"status": "skipped", "reason": response.status}
                ),
            )
        writer.write_json("05_response.json", response.to_dict())
        return response

    def _official_url(
        self,
        question: str,
        retrieval: RetrievalResult | None = None,
        *,
        prefer_education: bool = False,
    ) -> str | None:
        if retrieval is not None and retrieval.closest_official_page:
            return retrieval.closest_official_page

        education = [spec for spec in self.sources if spec.category == "education"]
        by_id = {spec.id: spec for spec in self.sources}

        # Refusal cards link an official educational page. When the question
        # names a supported fact, prefer the education page for that fact.
        if prefer_education:
            for fact_type in detect_fact_types(question):
                source_id = FACT_SOURCE_IDS.get(fact_type)
                spec = by_id.get(source_id) if source_id else None
                if spec is not None and spec.category == "education":
                    return spec.url
            if education:
                return education[0].url

        scheme_ids = set(detect_schemes(question, self.sources))
        for spec in self.sources:
            if spec.id in scheme_ids:
                return spec.url

        for fact_type in detect_fact_types(question):
            source_id = FACT_SOURCE_IDS.get(fact_type)
            if source_id and source_id in by_id:
                return by_id[source_id].url

        if education:
            return education[0].url
        return self.sources[0].url if self.sources else None

    def _citation_for_url(
        self,
        url: str | None,
        retrieval: RetrievalResult | None = None,
    ) -> Citation | None:
        if not url:
            return None
        for spec in self.sources:
            if spec.url == url:
                return Citation(url=spec.url, title=spec.title)
        if retrieval is not None:
            for chunk in retrieval.results:
                if chunk.source_url == url:
                    return Citation(url=url, title=chunk.source_title)
        return Citation(url=url, title=urlparse(url).netloc or "Official page")


def answer_question(question: str) -> QueryResponse:
    """Convenience wrapper for callers that do not need dependency injection."""

    return QueryOrchestrator().answer(question)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask one factual mutual fund question through the full pipeline."
    )
    parser.add_argument(
        "question",
        nargs="+",
        help="Question text, for example: \"What is the exit load on HDFC ELSS?\"",
    )
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()

    settings = load_settings()
    orchestrator = QueryOrchestrator(settings=settings)
    response = orchestrator.answer(question)
    print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
    return 0 if response.status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
