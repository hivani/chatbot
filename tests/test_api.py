from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import src.app.api as api_module
from src.app.api import create_app
from src.artifacts import ArtifactWriter, new_query_id
from src.query.orchestrator import Citation, QueryResponse


class FakeStore:
    def count(self) -> int:
        return 108


class FakeOrchestrator:
    retriever = SimpleNamespace(store=FakeStore())
    generator = SimpleNamespace(provider="fake", model="fake-v1")

    def __init__(self, response: QueryResponse | None = None):
        self.response = response
        self.questions: list[str] = []

    def answer(self, question: str) -> QueryResponse:
        self.questions.append(question)
        if self.response is not None:
            return self.response
        return QueryResponse(
            query_id=new_query_id(),
            status="answered",
            query=question,
            answer="Exit load: Nil.",
            citation=Citation(url="https://example.com/page", title="Example"),
            last_updated="2026-11-02T07:03:13Z",
            disclaimer="Facts-only. No investment advice.",
            refusal_reason=None,
            stage_artifacts={},
            validation={"sentence_count": 1},
        )


@pytest.fixture
def client():
    return TestClient(create_app(orchestrator=FakeOrchestrator()))


def test_query_returns_the_orchestrator_envelope(client):
    response = client.post("/query", json={"query": "What is the exit load?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered"
    assert payload["answer"] == "Exit load: Nil."
    assert payload["citation"]["title"] == "Example"


def test_query_rejects_empty_text(client):
    response = client.post("/query", json={"query": ""})

    assert response.status_code == 422


def test_health_reports_count_and_provider(client):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["chroma_count"] == 108
    assert payload["generator_provider"] == "fake"


def test_artifacts_are_served_from_disk(tmp_path, monkeypatch):
    query_id = new_query_id()
    writer = ArtifactWriter(tmp_path, query_id)
    writer.write_json("00_request.json", {"query": "test"})
    writer.write_text("03_prompt.txt", "prompt")

    monkeypatch.setattr(
        api_module,
        "_settings_cache",
        SimpleNamespace(paths=SimpleNamespace(artifacts_dir=tmp_path)),
    )
    client = TestClient(create_app(orchestrator=FakeOrchestrator()))

    response = client.get(f"/artifacts/{query_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_id"] == query_id
    assert payload["artifacts"]["00_request.json"] == {"query": "test"}
    assert payload["artifacts"]["03_prompt.txt"] == "prompt"


def test_unknown_artifacts_return_404(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_module,
        "_settings_cache",
        SimpleNamespace(paths=SimpleNamespace(artifacts_dir=tmp_path)),
    )
    client = TestClient(create_app(orchestrator=FakeOrchestrator()))

    response = client.get("/artifacts/q_20260101T000000Z_abcdef")

    assert response.status_code == 404


def test_invalid_query_id_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_module,
        "_settings_cache",
        SimpleNamespace(paths=SimpleNamespace(artifacts_dir=tmp_path)),
    )
    client = TestClient(create_app(orchestrator=FakeOrchestrator()))

    response = client.get("/artifacts/not-a-query-id")

    assert response.status_code == 404


def test_stitch_ui_shell_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert 'id="queryForm"' in body
    assert 'id="traceDrawer"' in body
    assert 'src="app.js"' in body
    assert "Facts-only. No investment advice." in body


def test_ui_assets_are_served(client):
    stylesheet = client.get("/styles.css")
    script = client.get("/app.js")

    assert stylesheet.status_code == 200
    assert "--accent: #00b386" in stylesheet.text
    assert script.status_code == 200
    assert 'fetch("/query"' in script.text
    assert "/artifacts/${encodeURIComponent(queryId)}" in script.text
