"""FastAPI surface for the same orchestrator used by Streamlit.

Run locally with:

    uvicorn src.app.api:app --reload
    uvicorn app:app --reload          # Vercel-compatible root entrypoint

Endpoints:

* ``GET /`` — the static Stitch UI
* ``POST /query`` — body ``{"query": "..."}`` → answer envelope
* ``GET /health`` — liveness, index count, retriever, embedding model, provider
* ``GET /artifacts/{query_id}`` — six stage artifacts for the inspector

The heavy RAG stack is imported lazily so the function can boot on Vercel and
serve the UI even if the vector index or model is not ready. On Vercel the
read-only bundle is copied to ``/tmp`` before Chroma or artifacts are opened.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.artifacts import ArtifactError, list_artifacts, read_artifact, read_json_artifact
from src.config import PROJECT_ROOT, Settings, load_settings

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from src.query.orchestrator import QueryOrchestrator

_settings_cache: Settings | None = None
_orchestrator: Any | None = None


def _on_vercel() -> bool:
    return bool(os.getenv("VERCEL"))


def _configure_vercel_environment() -> None:
    """Redirect caches to /tmp before heavy libraries are imported."""

    if not _on_vercel():
        return
    os.environ.setdefault("HOME", "/tmp")
    os.environ.setdefault("HF_HOME", "/tmp/huggingface")
    os.environ.setdefault(
        "SENTENCE_TRANSFORMERS_HOME", "/tmp/sentence-transformers"
    )
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


_configure_vercel_environment()


def _vercel_settings(settings: Settings) -> Settings:
    """Point mutable data at ``/tmp`` because Vercel's bundle is read-only."""

    if not _on_vercel():
        return settings

    target_root = Path("/tmp/growchatbot")
    data_dir = target_root / "data"
    bundled_data = PROJECT_ROOT / "data"
    if bundled_data.is_dir():
        shutil.copytree(bundled_data, data_dir, dirs_exist_ok=True)
    (target_root / "artifacts").mkdir(parents=True, exist_ok=True)

    paths = settings.paths.model_copy(
        update={
            "sources": data_dir / "sources.csv",
            "raw_dir": data_dir / "raw",
            "chunks_file": data_dir / "chunks" / "chunks.jsonl",
            "embeddings_dir": data_dir / "embeddings",
            "artifacts_dir": target_root / "artifacts",
        }
    )
    vector_store = settings.vector_store.model_copy(
        update={"persist_path": data_dir / "chroma"}
    )
    return settings.model_copy(
        update={"paths": paths, "vector_store": vector_store}
    )


def _settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = _vercel_settings(load_settings())
    return _settings_cache


def _get_orchestrator() -> QueryOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        # Imported here, not at module scope: Chroma/torch/sentence-transformers
        # are heavy and can fail on serverless cold starts. This keeps ``/``
        # and ``/health`` available for diagnostics.
        from src.query.orchestrator import QueryOrchestrator

        _orchestrator = QueryOrchestrator(settings=_settings())
    return _orchestrator


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def create_app(orchestrator: QueryOrchestrator | None = None) -> FastAPI:
    """Build the API, optionally with an injected orchestrator for tests."""

    app = FastAPI(title="Growchatbot API", version="1.0")

    def current_orchestrator() -> QueryOrchestrator:
        return orchestrator or _get_orchestrator()

    @app.get("/", include_in_schema=False)
    def index() -> Any:
        index_file = PROJECT_ROOT / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return {
            "service": "Growchatbot API",
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/styles.css", include_in_schema=False)
    def stylesheet() -> Any:
        return FileResponse(PROJECT_ROOT / "styles.css")

    @app.get("/app.js", include_in_schema=False)
    def script() -> Any:
        return FileResponse(PROJECT_ROOT / "app.js")

    assets_dir = PROJECT_ROOT / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.post("/query")
    def query(request: QueryRequest) -> dict[str, Any]:
        try:
            response = current_orchestrator().answer(request.query)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - report readiness, never crash
            raise HTTPException(
                status_code=503,
                detail={
                    "error": type(exc).__name__,
                    "message": (
                        "The RAG backend is not ready. Check /health and the "
                        "deployment logs."
                    ),
                },
            ) from exc
        return response.to_dict()

    @app.get("/health")
    def health() -> dict[str, Any]:
        try:
            instance = current_orchestrator()
            count = int(instance.retriever.store.count())
        except Exception as exc:  # noqa: BLE001 - health should not crash
            return {
                "status": "not_ready",
                "error": type(exc).__name__,
            }

        settings = _settings()
        retriever = getattr(instance, "retriever", None)
        lexical = bool(getattr(retriever, "lexical", False))
        return {
            "status": "ok" if count > 0 else "not_ready",
            "chroma_count": count,
            "index_count": count,
            "retriever": "lexical-bm25" if lexical else "vector",
            "collection": settings.vector_store.collection,
            "embedding_model": (
                "lexical-bm25" if lexical else settings.embedding.model
            ),
            "generator_provider": getattr(instance.generator, "provider", "unknown"),
        }

    @app.get("/artifacts/{query_id}")
    def artifacts(query_id: str) -> dict[str, Any]:
        root = Path(_settings().paths.artifacts_dir)
        try:
            names = list_artifacts(root, query_id)
            contents: dict[str, Any] = {}
            for name in names:
                if name.endswith(".json"):
                    contents[name] = read_json_artifact(root, query_id, name)
                else:
                    contents[name] = read_artifact(root, query_id, name)
        except (ArtifactError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not names:
            raise HTTPException(status_code=404, detail="No artifacts for this query")
        return {"query_id": query_id, "artifacts": contents}

    return app


app = create_app()
