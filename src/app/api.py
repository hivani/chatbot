"""Optional FastAPI surface for the same orchestrator used by Streamlit.

Run with:

    uvicorn src.app.api:app --reload

Endpoints:

* ``POST /query`` — body ``{"query": "..."}`` → answer envelope
* ``GET /health`` — liveness, Chroma count, embedding model, provider
* ``GET /artifacts/{query_id}`` — six stage artifacts for the inspector
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.artifacts import ArtifactError, list_artifacts, read_artifact, read_json_artifact
from src.config import load_settings
from src.query.orchestrator import QueryOrchestrator

_settings_cache = None
_orchestrator: QueryOrchestrator | None = None


def _settings():
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = load_settings()
    return _settings_cache


def _get_orchestrator() -> QueryOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = QueryOrchestrator(settings=_settings())
    return _orchestrator


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def create_app(orchestrator: QueryOrchestrator | None = None) -> FastAPI:
    """Build the API, optionally with an injected orchestrator for tests."""

    app = FastAPI(title="Growchatbot API", version="1.0")

    def current_orchestrator() -> QueryOrchestrator:
        return orchestrator or _get_orchestrator()

    @app.post("/query")
    def query(request: QueryRequest) -> dict[str, Any]:
        try:
            response = current_orchestrator().answer(request.query)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        return {
            "status": "ok" if count > 0 else "not_ready",
            "chroma_count": count,
            "collection": settings.vector_store.collection,
            "embedding_model": settings.embedding.model,
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
