"""Provider adapters for grounded answer generation.

v1 targets Groq. Provider/model ids come from configuration and ``.env``; they
are never hardcoded. The offline extractive generator exists so the demo and
tests can run without a key: it only copies lines from the cited chunk, never
invents facts, and is reported honestly in the completion artifact.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from src.config import Settings


class GeneratorError(RuntimeError):
    """Raised when a provider call fails."""


class GeneratorNotConfigured(GeneratorError):
    """Raised when the selected provider has no key/model implementation."""


@dataclass(frozen=True)
class Completion:
    """Raw provider result plus the metadata needed by the inspector."""

    provider: str
    model: str
    text: str
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "text": self.text,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
            "raw": self.raw,
        }


class Generator(Protocol):
    """Minimal interface used by the orchestrator."""

    provider: str
    model: str

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        chunks: Sequence[Any] | None = None,
        question: str = "",
        preferred_index: int = 1,
        fact_types: Sequence[str] = (),
    ) -> Completion:
        """Return one completion for the supplied messages."""


class GroqGenerator:
    """Groq chat-completions adapter with one transport retry."""

    provider = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 300,
        timeout_seconds: int = 20,
    ):
        if not api_key:
            raise GeneratorNotConfigured("GROQ_API_KEY is not set")
        if not model:
            raise GeneratorNotConfigured("GROQ_MODEL is not set")

        try:
            from groq import Groq
        except Exception as exc:  # noqa: BLE001 - optional dependency
            raise GeneratorNotConfigured(
                f"The groq package is not available: {exc}"
            ) from exc

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self._client = Groq(api_key=api_key, timeout=timeout_seconds)

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        chunks: Sequence[Any] | None = None,
        question: str = "",
        preferred_index: int = 1,
        fact_types: Sequence[str] = (),
    ) -> Completion:
        del chunks, question, preferred_index, fact_types
        started = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                request: dict[str, Any] = {
                    "model": self.model,
                    "messages": [dict(message) for message in messages],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
                # Prefer provider-enforced JSON, but retry without it in case a
                # model in the Groq catalogue does not support the parameter.
                if attempt == 0:
                    request["response_format"] = {"type": "json_object"}

                response = self._client.chat.completions.create(**request)
                choice = response.choices[0]
                text = choice.message.content or ""
                usage = getattr(response, "usage", None)
                latency_ms = int((time.perf_counter() - started) * 1000)

                return Completion(
                    provider=self.provider,
                    model=getattr(response, "model", self.model) or self.model,
                    text=text,
                    latency_ms=latency_ms,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    finish_reason=getattr(choice, "finish_reason", None),
                    raw={"attempts": attempt + 1},
                )
            except Exception as exc:  # noqa: BLE001 - transport/provider failure
                last_error = exc
                if attempt == 0:
                    time.sleep(0.4)

        raise GeneratorError(
            f"Groq generation failed after one retry: {type(last_error).__name__}"
        ) from last_error


# Keyword families used by the offline generator to select factual lines.
_FACT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "expense_ratio": ("expense ratio", "total expense"),
    "exit_load": ("exit load", "entry load"),
    "sip": ("sip", "systematic investment"),
    "lock_in": ("lock-in", "lock in", "lockin"),
    "riskometer": ("riskometer", "risk level"),
    "benchmark": ("benchmark",),
    "statement": ("statement", "capital gain", " consolidated account"),
}

_STOPWORDS = {
    "what", "which", "when", "where", "who", "whom", "whose", "why", "how",
    "is", "are", "was", "were", "the", "a", "an", "of", "for", "on", "in",
    "to", "and", "or", "does", "do", "did", "can", "could", "should", "would",
    "my", "me", "i", "we", "you", "it", "its", "this", "that", "please",
    "tell", "about", "with", "from", "at", "by", "scheme", "fund", "mutual",
}

_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _clean_segment(text: str) -> str:
    value = re.sub(r"\s*\|\s*", ": ", text.strip())
    value = re.sub(r"\s+", " ", value).strip(" -;")
    return value


def _strip_prefix(line: str, chunk: Any) -> str:
    title = str(getattr(chunk, "source_title", "") or "").strip()
    section = str(getattr(chunk, "section", "") or "").strip()
    candidates = []
    if title and section:
        candidates.append(f"{title} — {section}")
    if title:
        candidates.append(title)
    for prefix in candidates:
        if line.startswith(prefix):
            return line[len(prefix) :].lstrip(" .:-—|")
    return line


def _truncate_sentences(text: str, limit: int) -> str:
    ends = list(_SENTENCE_END.finditer(text))
    if len(ends) <= limit:
        return text
    return text[: ends[limit - 1].end()].strip()


class OfflineExtractiveGenerator:
    """Deterministic fallback that quotes the cited chunk without an LLM.

    This is not a substitute for the Groq path. It exists so the UI, tests,
    and artifact inspector can run end-to-end without an API key. The provider
    name appears in ``04_completion.json`` and the UI badge.
    """

    provider = "offline-extractive"
    model = "extractive-v1"

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        chunks: Sequence[Any] | None = None,
        question: str = "",
        preferred_index: int = 1,
        fact_types: Sequence[str] = (),
    ) -> Completion:
        del messages
        started = time.perf_counter()
        chunk_list = list(chunks or [])

        if not chunk_list:
            return self._completion(
                {
                    "answer": "The indexed sources do not contain enough information.",
                    "citation_index": None,
                    "used_chunk_ids": [],
                    "insufficient": True,
                },
                started,
            )

        index = preferred_index if 1 <= preferred_index <= len(chunk_list) else 1
        chunk = chunk_list[index - 1]
        text = str(getattr(chunk, "text", "") or "")

        keywords: list[str] = []
        for fact_type in fact_types:
            keywords.extend(_FACT_KEYWORDS.get(fact_type, ()))
        if not keywords:
            keywords = [
                word
                for word in re.findall(r"[a-z0-9]+", question.casefold())
                if len(word) > 3 and word not in _STOPWORDS
            ]

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        matched = [
            line
            for line in lines
            if any(keyword in line.casefold() for keyword in keywords)
        ]
        selected = matched[:2] or lines[:2]

        segments = [
            _clean_segment(_strip_prefix(line, chunk)) for line in selected
        ]
        segments = [segment for segment in segments if segment]
        if not segments:
            return self._completion(
                {
                    "answer": "The indexed source does not state this fact.",
                    "citation_index": None,
                    "used_chunk_ids": [],
                    "insufficient": True,
                },
                started,
            )

        fact_text = _truncate_sentences("; ".join(segments), limit=2)
        title = str(getattr(chunk, "source_title", "") or "the official page")
        answer = f"According to the indexed {title} page, {fact_text}."

        return self._completion(
            {
                "answer": answer,
                "citation_index": index,
                "used_chunk_ids": [str(getattr(chunk, "chunk_id", ""))],
                "insufficient": False,
            },
            started,
        )

    def _completion(self, payload: dict[str, Any], started: float) -> Completion:
        return Completion(
            provider=self.provider,
            model=self.model,
            text=json.dumps(payload, ensure_ascii=False),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={"mode": "offline-extractive"},
        )


def build_generator(
    settings: Settings,
    *,
    allow_offline_fallback: bool = True,
) -> Generator:
    """Select the configured provider, with an explicit local fallback."""

    provider = settings.llm.provider
    if provider != "groq":
        raise GeneratorNotConfigured(
            f"Provider {provider!r} is not implemented in v1; use groq."
        )

    key_env = "GROQ_API_KEY"
    api_key = os.getenv(key_env, "").strip()
    model = (settings.llm.model or os.getenv(settings.llm.model_env, "")).strip()

    if api_key and model:
        try:
            return GroqGenerator(
                api_key=api_key,
                model=model,
                temperature=settings.llm.temperature,
                max_tokens=settings.llm.max_tokens,
                timeout_seconds=settings.llm.timeout_seconds,
            )
        except GeneratorNotConfigured:
            if not allow_offline_fallback:
                raise

    if allow_offline_fallback:
        return OfflineExtractiveGenerator()

    if not api_key:
        raise GeneratorNotConfigured(
            f"{key_env} is required for llm.provider={provider!r}."
        )
    raise GeneratorNotConfigured(
        f"{settings.llm.model_env} is required for llm.provider={provider!r}."
    )
