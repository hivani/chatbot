"""Streamlit chat surface and six-artifact RAG inspector.

Run from the project root:

    streamlit run src/app/streamlit_app.py

The UI calls the orchestrator once per question, then reads the resulting
``artifacts/<query_id>/`` files from disk. The inspector never re-runs
retrieval. No PII fields, account linking, or query analytics are collected.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Disable Streamlit's usage telemetry and make the project root importable when
# Streamlit runs this file directly.
os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src.artifacts import (  # noqa: E402
    ArtifactError,
    list_artifacts,
    read_artifact,
    read_json_artifact,
)
from src.config import load_settings  # noqa: E402
from src.query.orchestrator import QueryOrchestrator  # noqa: E402

EXAMPLES = (
    "What is the exit load on HDFC ELSS?",
    "What is the expense ratio of HDFC Flexi Cap?",
    "What is the lock-in period for ELSS?",
)

STATUS_LABELS = {
    "answered": ("success", "Answered from official sources"),
    "refused_pii": ("warning", "Refused — personal data detected"),
    "refused_advice": ("warning", "Refused — investment advice"),
    "refused_performance": ("warning", "Refused — performance request"),
    "insufficient_context": ("warning", "Insufficient context"),
    "error": ("error", "Could not produce a validated answer"),
}

ARTIFACT_TABS = (
    ("00 Request", "00_request.json"),
    ("01 Guardrails", "01_guardrails.json"),
    ("02 Retrieval", "02_retrieval.json"),
    ("03 Prompt", "03_prompt.txt"),
    ("04 Completion", "04_completion.json"),
    ("05 Response", "05_response.json"),
)


@st.cache_resource(show_spinner="Loading the retrieval index and embedding model…")
def get_orchestrator() -> QueryOrchestrator:
    return QueryOrchestrator(settings=load_settings())


def _json_artifact(root: Path, query_id: str, name: str) -> Any | None:
    try:
        return read_json_artifact(root, query_id, name)
    except (ArtifactError, ValueError) as exc:
        st.warning(f"{name}: {exc}")
        return None


def _text_artifact(root: Path, query_id: str, name: str) -> str | None:
    try:
        return read_artifact(root, query_id, name)
    except ArtifactError as exc:
        st.warning(f"{name}: {exc}")
        return None


def _render_exchange(exchange: dict[str, Any]) -> None:
    with st.chat_message("user"):
        st.markdown(exchange.get("query", ""))

    with st.chat_message("assistant"):
        status = str(exchange.get("status", "error"))
        level, label = STATUS_LABELS.get(status, ("error", status))
        with st.container(border=True):
            if level == "success":
                st.success(label)
            elif level == "warning":
                st.warning(label)
            else:
                st.error(label)

            st.markdown(exchange.get("answer", ""))

            citation = exchange.get("citation")
            if isinstance(citation, dict) and citation.get("url"):
                title = citation.get("title") or "Official source"
                st.markdown(f"[{title}]({citation['url']})")

            if exchange.get("last_updated"):
                st.caption(
                    "Last updated from sources: "
                    f"{exchange['last_updated']}"
                )

            st.caption(exchange.get("disclaimer", "Facts-only. No investment advice."))


def _render_retrieval(payload: dict[str, Any]) -> None:
    results = payload.get("results") or []
    if results:
        st.dataframe(
            [
                {
                    "rank": item.get("rank"),
                    "score": round(float(item.get("score", 0.0)), 4),
                    "doc_id": item.get("doc_id"),
                    "section": item.get("section"),
                    "chunk_id": item.get("chunk_id"),
                }
                for item in results
            ],
            width="stretch",
            hide_index=True,
        )
    st.json(payload)


def _render_inspector(root: Path, exchanges: list[dict[str, Any]]) -> None:
    with st.expander("RAG inspector — six stage artifacts", expanded=False):
        st.caption(
            "These panels read `artifacts/<query_id>/` from disk. "
            "Opening the inspector does not re-run retrieval or generation."
        )
        if not exchanges:
            st.info("Ask a question first, then inspect its six stage artifacts here.")
            return

        selected_index = st.selectbox(
            "Query",
            options=list(range(len(exchanges))),
            format_func=lambda index: (
                f"{exchanges[index].get('query_id', '')} — "
                f"{str(exchanges[index].get('query', ''))[:70]}"
            ),
        )
        exchange = exchanges[selected_index]
        query_id = str(exchange.get("query_id", ""))
        if not query_id:
            st.error("This exchange has no query id.")
            return

        st.caption(
            f"Reading from `artifacts/{query_id}/` · "
            f"files: {', '.join(list_artifacts(root, query_id)) or 'none'}"
        )

        tabs = st.tabs([label for label, _name in ARTIFACT_TABS])
        for tab, (label, filename) in zip(tabs, ARTIFACT_TABS):
            with tab:
                if filename.endswith(".json"):
                    payload = _json_artifact(root, query_id, filename)
                    if payload is not None:
                        if filename == "02_retrieval.json" and isinstance(
                            payload, dict
                        ):
                            _render_retrieval(payload)
                        else:
                            st.json(payload)
                else:
                    text = _text_artifact(root, query_id, filename)
                    if text is not None:
                        st.code(text, language="text")


def main() -> None:
    st.set_page_config(
        page_title="Growchatbot — Mutual Fund FAQ",
        page_icon="📊",
        layout="wide",
    )

    settings = load_settings()
    st.session_state.setdefault("exchanges", [])
    st.session_state.setdefault("pending_question", None)

    try:
        orchestrator = get_orchestrator()
        chunk_count = int(orchestrator.retriever.store.count())
    except Exception as exc:  # noqa: BLE001 - show an actionable startup error
        st.error(
            "The retrieval backend could not start. Check the model download, "
            "`config.yaml`, and the Chroma directory."
        )
        st.exception(exc)
        st.stop()

    with st.sidebar:
        st.title("Growchatbot")
        st.caption("Official mutual fund FAQs · facts only")
        st.metric("Indexed chunks", chunk_count)
        st.caption(
            f"Collection: `{settings.vector_store.collection}`\n\n"
            f"Embedding model: `{settings.embedding.model}`"
        )
        provider = getattr(orchestrator.generator, "provider", "unknown")
        model = getattr(orchestrator.generator, "model", "unknown")
        if provider == "offline-extractive":
            st.warning(
                "No `GROQ_API_KEY` is set, so the offline extractive generator "
                "is active. It quotes the cited chunk without an LLM. Add "
                "`GROQ_API_KEY` and `GROQ_MODEL` to `.env` to use Groq."
            )
        else:
            st.success(f"Generator: `{provider}` / `{model}`")

        st.divider()
        st.markdown("**Rebuild the corpus**")
        st.code(
            "python -m src.ingest.pipeline --stage all --rebuild",
            language="bash",
        )
        st.divider()
        st.markdown(f"**{settings.app.disclaimer}**")
        st.caption(
            "This demo does not collect PII, link accounts, or capture query "
            "analytics. Per-query artifacts stay in the local `artifacts/` folder."
        )

    st.title("Growchatbot — Mutual Fund FAQ")
    st.markdown(
        "Ask a factual question about the HDFC scheme pages and investor "
        "education pages in the indexed corpus. Answers cite one official "
        "source and show when it was last updated."
    )
    st.info(f"**{settings.app.disclaimer}**")

    if chunk_count == 0:
        st.warning(
            "The vector store is empty. Build it before asking questions:"
        )
        st.code(
            "python -m src.ingest.pipeline --stage all --rebuild",
            language="bash",
        )
        st.stop()

    st.markdown("**Try an example**")
    columns = st.columns(len(EXAMPLES))
    for column, example in zip(columns, EXAMPLES):
        if column.button(example, width="stretch"):
            st.session_state.pending_question = example
            st.rerun()

    st.caption(
        "🔒 Don't paste PAN, Aadhaar, account numbers, OTPs, email, or phone "
        "numbers. Personal data is refused and redacted before anything is "
        "stored."
    )

    typed_question = st.chat_input(
        "Ask about expense ratio, exit load, SIP, lock-in, riskometer, or a statement…"
    )
    pending = st.session_state.pop("pending_question", None)
    question = (pending or typed_question or "").strip()

    if question:
        with st.spinner("Checking the indexed official sources…"):
            try:
                response = orchestrator.answer(question)
                exchange = response.to_dict()
            except Exception as exc:  # noqa: BLE001 - keep the UI responsive
                st.error(
                    "The query could not be completed. No unvalidated answer "
                    "was returned."
                )
                st.exception(exc)
                exchange = None

        if exchange is not None:
            st.session_state.exchanges.append(exchange)

    for exchange in st.session_state.exchanges:
        _render_exchange(exchange)

    _render_inspector(
        Path(settings.paths.artifacts_dir),
        st.session_state.exchanges,
    )


if __name__ == "__main__":
    main()
