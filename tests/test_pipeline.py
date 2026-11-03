from src.ingest import pipeline


def test_run_all_runs_stages_in_order_and_propagates_rebuild(monkeypatch):
    calls = []

    def fake_load(**_kwargs):
        calls.append("load")
        return 0

    def fake_load_docs(**_kwargs):
        calls.append("load-docs")
        return 0

    def fake_chunk(**_kwargs):
        calls.append("chunk")
        return 0

    def fake_embed(**_kwargs):
        calls.append("embed")
        return 0

    def fake_index(**kwargs):
        calls.append("index")
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(pipeline, "run_load", fake_load)
    monkeypatch.setattr(pipeline, "run_load_docs", fake_load_docs)
    monkeypatch.setattr(pipeline, "run_chunk", fake_chunk)
    monkeypatch.setattr(pipeline, "run_embed", fake_embed)
    monkeypatch.setattr(pipeline, "run_index", fake_index)

    status = pipeline.run_all(
        chunks_file="chunks.jsonl",
        embeddings_dir="embeddings",
        rebuild=True,
    )

    assert status == 0
    assert calls[:5] == ["load", "load-docs", "chunk", "embed", "index"]
    assert calls[5]["rebuild"] is True
    assert calls[5]["chunks_file"] == "chunks.jsonl"
    assert calls[5]["embeddings_dir"] == "embeddings"


def test_run_all_stops_when_load_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(
        pipeline,
        "run_load",
        lambda **_kwargs: calls.append("load") or 1,
    )
    monkeypatch.setattr(
        pipeline,
        "run_load_docs",
        lambda **_kwargs: calls.append("load-docs") or 0,
    )
    monkeypatch.setattr(
        pipeline,
        "run_chunk",
        lambda **_kwargs: calls.append("chunk") or 0,
    )
    monkeypatch.setattr(
        pipeline,
        "run_embed",
        lambda **_kwargs: calls.append("embed") or 0,
    )
    monkeypatch.setattr(
        pipeline,
        "run_index",
        lambda **_kwargs: calls.append("index") or 0,
    )

    assert pipeline.run_all(rebuild=True) == 1
    assert calls == ["load"]
